#!/usr/bin/env python

import argparse
import json
import math
import os

import jinja2
import requests
import yaml

from tabulate import tabulate


def to_mb(v):
    return str(math.ceil(float(v) / (1024*1024))) + 'Mi'


def to_millicore(v):
    return str(round(float(v) * 1000)) + 'm'


def promql_j2(proms, template_name, **kwargs):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    filename = os.path.join(dir_path, 'promql', template_name)

    with open(filename, 'r') as f:
        template = jinja2.Template(f.read())

    query = template.render(kwargs)
    return promql(proms, query)


def promql(proms, query):
    results = {}

    params = {'query': query}
    for prom in proms:
        headers = {}

        if prom.get('authorization'):
            headers['Authorization'] = prom['authorization']

        response = requests.get(prom['url'],
                                params=params,
                                headers=headers).json()

        results[prom['name']] = response['data']['result']

    return results


def store_metrics(metrics_dict, metrics_result, metric_name,
                  handler=None):
    for prom_name, metrics in metrics_result.items():
        for info in metrics:
            metric = info['metric']
            value = info['value'][1]

            namespace = metric['namespace']
            app = metric.get('label_app')
            container = metric.get('container_name')

            if app is None:
                continue

            if handler is not None:
                value = handler(value)

            key = (prom_name, namespace, app, container)

            metrics_dict.setdefault(key, {})
            metrics_dict[key][metric_name] = value


def main():
    parser = argparse.ArgumentParser(
        description='Generate resources requests/limits report')

    # config file
    parser.add_argument('--config', help='config file', required=True)

    # output format
    parser.add_argument('--format', choices=['json', 'plain', 'html'],
                        default='json')

    args = parser.parse_args()

    # read config
    with open(args.config, 'r') as config_file:
        config = yaml.safe_load(config_file)

    proms = config['prometheus']
    metrics = {}

    # memory usage
    mem_usage = promql_j2(proms, 'quantile-per-container.j2',
                          metric='container_memory_usage_bytes',
                          quantile='0.8',
                          timerange=config['timerange'])
    store_metrics(metrics, mem_usage, 'memory_usage_q0.8', handler=to_mb)

    mem_usage = promql_j2(proms, 'quantile-per-container.j2',
                          metric='container_memory_usage_bytes',
                          quantile='1',
                          timerange=config['timerange'])
    store_metrics(metrics, mem_usage, 'memory_usage_max', handler=to_mb)

    # memory requests
    mem_reqs_metric = 'kube_pod_container_resource_requests_memory_bytes'
    mem_requests = promql_j2(proms, 'add-label-app.j2', metric=mem_reqs_metric)
    store_metrics(metrics, mem_requests, 'mem_requests', handler=to_mb)

    # memory limits
    mem_limits_metric = 'kube_pod_container_resource_limits_memory_bytes'
    mem_limits = promql_j2(proms, 'add-label-app.j2', metric=mem_limits_metric)
    store_metrics(metrics, mem_limits, 'mem_limits', handler=to_mb)

    # cpu usage
    cpu_usage_metric = ('namespace_pod_name_container_name:'
                        'container_cpu_usage_seconds_total:sum_rate')

    cpu_usage = promql_j2(proms, 'quantile-per-container.j2',
                          metric=cpu_usage_metric,
                          quantile='0.8',
                          timerange=config['timerange'])
    store_metrics(metrics, cpu_usage, 'cpu_usage_q0.8', handler=to_millicore)

    cpu_usage = promql_j2(proms, 'quantile-per-container.j2',
                          metric=cpu_usage_metric,
                          quantile='1',
                          timerange=config['timerange'])
    store_metrics(metrics, cpu_usage, 'cpu_usage_max', handler=to_millicore)

    # cpu requests
    cpu_reqs_metric = 'kube_pod_container_resource_requests_cpu_cores'
    cpu_requests = promql_j2(proms, 'add-label-app.j2', metric=cpu_reqs_metric)
    store_metrics(metrics, cpu_requests, 'cpu_requests', handler=to_millicore)

    # cpu limits
    cpu_limits_metric = 'kube_pod_container_resource_limits_cpu_cores'
    cpu_limits = promql_j2(proms, 'add-label-app.j2', metric=cpu_limits_metric)
    store_metrics(metrics, cpu_limits, 'cpu_limits', handler=to_millicore)

    if args.format == 'json':
        metrics = {'/'.join(k): v for k, v in metrics.items()}
        print(json.dumps(metrics, indent=4))
    else:
        def gen_row_table(params, values):
            return [
                *params,
                values.get('memory_usage_q0.8'),
                values.get('memory_usage_max'),
                values.get('mem_requests'),
                values.get('mem_limits'),
                values.get('cpu_usage_q0.8'),
                values.get('cpu_usage_max'),
                values.get('cpu_requests'),
                values.get('cpu_limits')
            ]

        table_data = [gen_row_table(params, values)
                      for params, values in metrics.items()]

        table_headers = [
            'cluster', 'namespace', 'app', 'container',
            'memory_usage_q0.8',
            'memory_usage_max',
            'mem_requests',
            'mem_limits',
            'cpu_usage_q0.8',
            'cpu_usage_max',
            'cpu_requests',
            'cpu_limits'
        ]

        table = tabulate(sorted(table_data), table_headers,
                         tablefmt=args.format)
        print(table)


if __name__ == '__main__':
    main()

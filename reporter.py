#!/usr/bin/env python

import os
import json
import math

import yaml
import jinja2
import requests


# read config
with open('config.yaml', 'r') as config_file:
    CONFIG = yaml.safe_load(config_file)


def to_mb(v):
    return math.ceil(float(v) / (1024*1024))


def to_float(v):
    return float(v)


def round_2(v):
    return round(float(v), 2)


def promql_j2(template_name, **kwargs):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    filename = os.path.join(dir_path, 'promql', template_name)

    with open(filename, 'r') as f:
        template = jinja2.Template(f.read())

    query = template.render(kwargs)
    return promql(query)


def promql(query):
    results = {}

    params = {'query': query}
    for prom in CONFIG['prometheus']:
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
            app = metric['label_app']
            container = metric.get('container_name')

            if handler is not None:
                value = handler(value)

            key = "/".join([prom_name, namespace, app, container])

            metrics_dict.setdefault(key, {})
            metrics_dict[key][metric_name] = value


def main():
    metrics = {}

    # memory usage
    mem_usage = promql_j2('quantile-per-container.j2',
                          metric='container_memory_usage_bytes',
                          quantile='0.8',
                          timerange=CONFIG['timerange'])
    store_metrics(metrics, mem_usage, 'memory_usage_q0.8', handler=to_mb)

    # memory requests
    mem_reqs_metric = 'kube_pod_container_resource_requests_memory_bytes'
    mem_requests = promql_j2('add-label-app.j2', metric=mem_reqs_metric)
    store_metrics(metrics, mem_requests, 'mem_requests', handler=to_mb)

    # memory limits
    mem_limits_metric = 'kube_pod_container_resource_limits_memory_bytes'
    mem_limits = promql_j2('add-label-app.j2', metric=mem_limits_metric)
    store_metrics(metrics, mem_limits, 'mem_limits', handler=to_mb)

    # cpu usage
    cpu_usage_metric = ('namespace_pod_name_container_name:'
                        'container_cpu_usage_seconds_total:sum_rate')

    cpu_usage = promql_j2('quantile-per-container.j2',
                          metric=cpu_usage_metric,
                          quantile='0.8',
                          timerange=CONFIG['timerange'])
    store_metrics(metrics, cpu_usage, 'cpu_usage_q0.8', handler=round_2)

    # cpu requests
    cpu_reqs_metric = 'kube_pod_container_resource_requests_cpu_cores'
    cpu_requests = promql_j2('add-label-app.j2', metric=cpu_reqs_metric)
    store_metrics(metrics, cpu_requests, 'cpu_requests', handler=to_float)

    # cpu limits
    cpu_limits_metric = 'kube_pod_container_resource_limits_cpu_cores'
    cpu_limits = promql_j2('add-label-app.j2', metric=cpu_limits_metric)
    store_metrics(metrics, cpu_limits, 'cpu_limits', handler=to_float)

    print(json.dumps(metrics))


if __name__ == '__main__':
    main()

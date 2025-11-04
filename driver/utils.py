import csv

import pandas as pd

# Initialize CSV file with headers
def init_csv(csv_file):
    headers = [
        'timestamp', 
        'service', 
        'cpu.quota.used.percent', 
        'memory.limit.used.percent', 
        'jvm.heap.used.percent',
        'jvm.gc.global.time', 
        'kubernetes.deployment.replicas.available', 
        'net.http.request.time', 
        'net.request.count.in', 
        'net.http.error.count',
        'net.request.time.in',
        'net.bytes.in',
        'net.bytes.out',
        'net.bytes.total',
        'jvm.nonHeap.used.percent',
        'jvm.thread.count',
        'jvm.gc.global.count'
    ]
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

def append_to_csv(csv_file, timestamp, data_dict, service_to_use):
    metric_map = {
        ("cpu.quota.used.percent", "avg"): "cpu.quota.used.percent",
        ("memory.limit.used.percent", "avg"): "memory.limit.used.percent",
        ("jvm.heap.used.percent", "avg"): "jvm.heap.used.percent",
        ("jvm.gc.global.time", "avg"): "jvm.gc.global.time",
        ("kubernetes.deployment.replicas.available", "max"): "kubernetes.deployment.replicas.available",
        ("net.http.request.time", "max"): "net.http.request.time",
        ("net.request.count.in", "sum"): "net.request.count.in",
        ("net.http.error.count", "sum"): "net.http.error.count",
        ("net.request.time.in", "max"): "net.request.time.in",
        ("net.bytes.in", "max"): "net.bytes.in",
        ("net.bytes.out", "max"): "net.bytes.out",
        ("net.bytes.total", "max"): "net.bytes.total",
        ("jvm.nonHeap.used.percent", "avg"): "jvm.nonHeap.used.percent",
        ("jvm.thread.count", "max"): "jvm.thread.count",
        ("jvm.gc.global.count", "sum"): "jvm.gc.global.count"
    }

    service_data = {svc: {col: None for col in metric_map.values()} for svc in service_to_use}

    for (metric_id, agg), res in data_dict.items():
        if (metric_id, agg) not in metric_map:
            continue
            
        try:
            header = metric_map[(metric_id, agg)]
            df = pd.DataFrame([{
                "timestamp": e['t'], "service": e['d'][0], "value": e['d'][1]
            } for e in res["data"]])
            
            df_filtered = df[df['service'].isin(service_to_use)]
            
            if not df_filtered.empty:
                avg_values = df_filtered.groupby("service")["value"].mean()
                
                for svc, val in avg_values.items():
                    if svc in service_to_use:
                        service_data[svc][header] = val
        except Exception as e:
            print(f"Error processing metric {metric_id} with aggregation {agg}: {e}")
            continue

    try:
        with open(csv_file, "a", newline='') as f:
            writer = csv.writer(f)
            for svc in service_to_use:
                row = [
                    timestamp,
                    svc,
                    service_data[svc].get("cpu.quota.used.percent"),
                    service_data[svc].get("memory.limit.used.percent"),
                    service_data[svc].get("jvm.heap.used.percent"),
                    service_data[svc].get("jvm.gc.global.time"),
                    service_data[svc].get("kubernetes.deployment.replicas.available"),
                    service_data[svc].get("net.http.request.time"),
                    service_data[svc].get("net.request.count.in"),
                    service_data[svc].get("net.http.error.count"),
                    service_data[svc].get("net.request.time.in"),
                    service_data[svc].get("net.bytes.in"),
                    service_data[svc].get("net.bytes.out"),
                    service_data[svc].get("net.bytes.total"),
                    service_data[svc].get("jvm.nonHeap.used.percent"),
                    service_data[svc].get("jvm.thread.count"),
                    service_data[svc].get("jvm.gc.global.count"),
                ]
                writer.writerow(row)
        print(f"Data for timestamp {timestamp} appended to CSV successfully")
    except Exception as e:
        print(f"Error writing to CSV: {e}")
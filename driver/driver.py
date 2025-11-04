import os
import json
import time
import csv
from datetime import datetime

from dotenv import load_dotenv

from mapek.Knowledge import Knowledge
from mapek.Monitor import Monitor
from mapek.Analyzer import Analyzer
from mapek.Planner import Planner
from mapek.Executor import Executor
from utils import init_csv, append_to_csv

def main():
    # Create a CSV file for the dataset
    csv_file = "datasets/metrics_dataset.csv"
    if not os.path.exists('datasets'):
        os.mkdir('datasets')

    # Read .env file
    load_dotenv()

    # Initialize parameters
    guid = os.getenv("GUID")
    apikey = os.getenv("APIKEY")
    url = os.getenv("URL")
    sleep = int(os.getenv("SLEEP"))

    # Target service
    service_to_use = [
        "acmeair-mainservice",
        "acmeair-authservice",
        "acmeair-flightservice",
        "acmeair-customerservice",
        "acmeair-bookingservice"
    ]

    current_configs = {svc: {"cpu": 500, "memory": 512, "replica": 1} for svc in service_to_use}

    # Metrics settings
    monitor_metrics = [
        # avg
        ("jvm.heap.used.percent", "avg"),
        ("jvm.gc.global.time", "avg"),
        ("jvm.nonHeap.used.percent", "avg"),
        ("cpu.quota.used.percent", "avg"),
        ("memory.limit.used.percent", "avg"),
        ("net.request.time.in", "avg"),
        # max
        ("jvm.thread.count", "max"),
        ("net.http.request.time", "max"),
        ("net.request.time.in", "max"),
        ("net.bytes.in", "max"),
        ("net.bytes.out", "max"),
        ("net.bytes.total", "max"),
        ("kubernetes.deployment.replicas.available", "max"),
        # sum
        ("jvm.gc.global.count", "sum"),
        ("net.request.count.in", "sum"),
        ("net.http.error.count", "sum"),
        ("net.bytes.total", "sum"),
    ]

    analyze_metrics = [
        # Four Golden Signals
        # Latency
        ("net.request.time.in", "avg"),
        ("net.request.time.in", "max"),
        # Traffic
        ("net.request.count.in", "sum"),
        ("net.bytes.total", "sum"),
        # Errors
        ("net.http.error.count", "sum"),
        # Saturation
        ("cpu.quota.used.percent", "avg"),
        ("memory.limit.used.percent", "avg"),
        # Other
        ("jvm.gc.global.time", "avg"),
    ]

    # Initialize CSV file
    init_csv(csv_file)
    
    # Initialize components
    knowledge = Knowledge("./mapek/knowledge.json")
    resources = knowledge.get_resources()
    current_configs = {
            svc: {
                "requests": {
                    "cpu": resources[svc]["requests"]["cpu"],
                    "memory": resources[svc]["requests"]["memory"]
                },
                "limits": {
                    "cpu": resources[svc]["limits"]["cpu"],
                    "memory": resources[svc]["limits"]["memory"]
                },
                "replica": resources[svc]["replica"]
            }
            for svc in service_to_use
    }

    monitor = Monitor(url, apikey, guid, sleep)
    analyzer = Analyzer(analyze_metrics, service_to_use, knowledge.get_threshold(), knowledge.get_weight())
    planner = Planner(service_to_use, knowledge.get_resource_limitations(), knowledge.get_resource_limitations(), knowledge.get_threshold()["roi"])
    executor = Executor()

    print("")
    print("Starting MAPE-K adaptation loop...")
    cycle_count = 0

    # Start monitor and analyze
    while True:
        cycle_count += 1
        print(f"\n=== Adaptation Cycle {cycle_count} ===")
        print("")
        # MONITOR: Collect metrics
        print("[Monitoring Stage]")
        print("Getting metrics from IBM Cloud...")
        print("")
        data_dict = {}
        for metric, agg in monitor_metrics:
            res = monitor.fetch_data_from_ibm(metric, agg)
            if res:
                data_dict[(metric, agg)] = res
            else:
                print(f"Failed to fetch {metric} with {agg} aggregation")
        
        # ANALYZE: Process metrics
        print("[Analyzing Stage]")
        analysis_results = analyzer.process_data(data_dict)
        if len(analysis_results) == 0:
            print("Need to gather more data to continue, preventing from scaling flapping")
            time.sleep(sleep)
            continue

        # PLAN: Generate adaptation decisions
        print("[Planning Stage]")
        decisions, new_configs, system_situations = planner.evaluate_services(analysis_results, current_configs)
        print("")

        # EXECUTE: Apply adaptations
        print("[Executing Stage]")
        success = executor.execute_plan(decisions, current_configs, system_situations)
        if success:
            print("Successfully executed adaptation")
            current_configs = new_configs
        else:
            print("Failed to execute adaptation")

        # KNOWLEDGE: Store data with adaptation information
        timestamp = datetime.now().isoformat()
        append_to_csv(csv_file, timestamp, data_dict, service_to_use)

        # wait for next round
        time.sleep(sleep)

if __name__ == "__main__":
    main()
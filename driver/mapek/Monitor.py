import os
import json

from sdcclient import IbmAuthHelper, SdMonitorClient

class Monitor:
    def __init__(self, url, api_key, guid, sleep):
        ibm_headers = IbmAuthHelper.get_headers(url, api_key, guid)
        self.sdclient = SdMonitorClient(sdc_url=url, custom_headers=ibm_headers)
        self.START = -sleep
        self.END = 0
        self.SAMPLING = 10
        self.FILTER = 'kube_namespace_name="acmeair-group6"'

    def fetch_data_from_ibm(self, id, aggregation):
        metric = [
            {"id": "kubernetes.deployment.name"},  # segmentation by deployment
            {"id": id, "aggregations": {"time": aggregation, "group": "avg"}}
        ]
        try:
            ok, res = self.sdclient.get_data(
                metrics=metric, 
                start_ts=self.START, 
                end_ts=self.END,
                sampling_s=self.SAMPLING, 
                filter=self.FILTER
            )
            if not ok:
                print(f"Error fetching {id}: {res}")
                return None
            # Save raw JSON
            if not os.path.exists('datasets/raw'):
                os.makedirs('datasets/raw')
            filename = "datasets/raw/" + id.replace(".", "_") + "_" + aggregation + "_metric.json"
            with open(filename, "w") as outfile:
                json.dump(res, outfile)
            return res
        except Exception as e:
            print(f"Exception occurred while fetching {id}: {e}")
            return None
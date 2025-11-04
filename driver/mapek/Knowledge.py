import json
import os

class Knowledge:

    def __init__(self, file_path = "./knowledge.json"):
        self.file_path = file_path
        self.data = self._load_json()
        self.last_modified = os.path.getmtime(file_path)

    def _load_json(self):
        if not os.path.exists(self.file_path):
            print(f"{self.file_path} not found. Creating an empty knowledge base.")
            return None
        with open(self.file_path, "r") as f:
            return json.load(f)
    
    def _save_json(self):
        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=2)
        print(f"Knowledge file updated: {self.file_path}")

    def get(self):
        return {
            "thresholds": self.data.get("thresholds", {}),
            "weights": self.data.get("weights", {})
        }
    
    def get_threshold(self):
        return self.data.get("thresholds", {})

    def get_weight(self):
        return self.data.get("weights", {})

    def get_resources(self):
        return self.data.get("resources", {})

    def get_resource_limitations(self):
        return self.data.get("resources_limitations", {})
    
    def set_threshold(self, metric, key, value):
        if "thresholds" not in self.data:
            self.data["thresholds"] = {}
        if metric not in self.data["thresholds"]:
            self.data["thresholds"][metric] = {}
        if key == "error_rate":
            self.data["thresholds"][metric] = value
        else:
            self.data["thresholds"][metric][key] = value
        self._save_json()

    def set_weight(self, metric, value):
        if "weights" not in self.data:
            self.data["weights"] = {}
        self.data["weights"][metric] = value
        self._save_json()

    def set_resource_config(self, service_name, resource_data):
        if "resources" not in self.data:
            self.data["resources"] = {}
        self.data["resources"][service_name] = resource_data
        self._save_json()

    def reload_if_updated(self):
        modified = os.path.getmtime(self.file_path)
        if modified != self.last_modified:
            self.data = self._load_json()
            self.last_modified = modified
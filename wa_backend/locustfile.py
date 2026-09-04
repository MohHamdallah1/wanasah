import os
from locust import HttpUser, task, between
from dotenv import load_dotenv

load_dotenv()

class PureDatabaseConcurrencyTester(HttpUser):
    # لا يوجد انتظار إطلاقاً (0 ثانية). ضغط جنوني ومباشر
    wait_time = between(0.0, 0.0) 

    def on_start(self):
        self.headers = {}
        res = self.client.post("/login", json={"company_code": "WNS-01", "username": "admin_1", "password": "password"}, name="/login")
        if res.status_code == 200:
            self.headers = {"Authorization": f"Bearer {res.json()['token']}"}
            locs = self.client.get("/warehouse/locations", headers=self.headers, name="/warehouse/locations").json()
            self.wns_main_loc = next((l["id"] for l in locs if "MAIN" in l["code"].upper()), locs[0]["id"])
            self.wns_sec_loc = next((l["id"] for l in locs if "SEC" in l["code"].upper()), locs[-1]["id"])
            
            inv = self.client.get(f"/warehouse/inventory?location_id={self.wns_main_loc}", headers=self.headers, name="/warehouse/inventory").json()
            self.wns_prod_id = inv[0]["id"]

    @task
    def attack_pure_dispatch(self):
        if not all([self.wns_main_loc, self.wns_sec_loc, self.wns_prod_id]):
            return

        payload = {
            "source_location_id": self.wns_main_loc,
            "destination_location_id": self.wns_sec_loc,
            "items": [{"product_variant_id": self.wns_prod_id, "quantity": 1}]
        }
        
        with self.client.post("/warehouse/unified/transfer/dispatch", json=payload, headers=self.headers, name="/dispatch_db_test", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 400 and "الرصيد المتاح لا يغطي" in response.text:
                # هذا هو الإثبات أن أقفال قاعدة البيانات تعمل وتمنع الرصيد السالب
                response.success()
            else:
                response.failure(f"CRITICAL FAIL {response.status_code}: {response.text}")
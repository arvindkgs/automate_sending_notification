# Load test Notifications
import json
import logging
import ssl
import time
import traceback
import unittest
import warnings
from datetime import datetime

import requests
import stomper
from mailosaur import MailosaurClient
from mailosaur.models import SearchCriteria
from websocket import create_connection, WebSocketBadStatusException

#Editable
SERVICE_NAME = "load-test"
NO_OF_NOTIFICATIONS = 100
rainier_url = "https://rainier.local/"
password = "Rainier!20"

#Non-Editable
warnings.filterwarnings("ignore")
token = None
service_token = None
base_tenant_id = None
roleIdMap = None
BASE_ADMIN_USERNAME = "iotnms-admin@cisco.com"
MAILOSAUR_SERVER_NAME = "ogmzlfga"
MAILOSAUS_API_KEY = "MVdqc1zgPF8rtHn"


class LoadTest(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter('ignore')

    def test_notifications(self):
        global token
        token = self.getToken()
        global service_token
        service_token = self.getServiceToken()
        global base_tenant_id
        base_tenant_id = self.getBaseTenantId()
        global roleIdMap
        roleIdMap = self.getRoleIdMap()
        tenant_name = "notification-test-tenant-1"
        username = "nobody." + MAILOSAUR_SERVER_NAME + "@mailosaur.io"
        seconds_since_epoch = datetime.now().timestamp()

        #Create User
        user_id = self.createUser(username)
        print("created user-id: "+user_id)

        #Create tenant
        tenant_id = self.createTenant(tenant_name, [username])
        print("created tenant-id: "+tenant_id)

        #Create subscription
        self.createSubscription(SERVICE_NAME, tenant_id, user_id, username)

        body = "This is Sample Event one sent - " + str(seconds_since_epoch)
        try:
            #Generate and send notification
            ws = create_connection('ws://localhost:8080/audit/ws/audit-ingest', header={"Authorization":"Bearer "+service_token}, sslopt={"cert_reqs": ssl.CERT_NONE})
            print("Sending +"+NO_OF_NOTIFICATIONS+" notification, Body: "+body)
            msg = stomper.Frame()
            msg.cmd = 'SEND'
            msg.headers = {'destination': '/events/post', 'content_type': 'application/json', 'receipt': 'new-receipt'}

            msg.body = json.dumps({"tenant-id": tenant_id, "severity": "CRITICAL",
                                   "event-message": body, "event-name": SERVICE_NAME + "Asset",
                                   "time": int(round(time.time() * 1000)), "event-type": SERVICE_NAME + "down", "elementId": "oldvalue1",
                                   "neId": "newvalue1", "ne-kind": "userid6"})
            for i in range(NO_OF_NOTIFICATIONS):
                ws.send(msg.pack())
            ws.close()
        except WebSocketBadStatusException as err:
            print("-----Exception while trying to send notification via websocket-----")
            print(err)
            print(traceback.print_exc())
            print("-------------------------------------------------------------------")
        finally:
            #Wait till all notifications are read from queue
            print("Waiting for handling notifications from queue, before cleanup .....")
            time.sleep(120)
            print("Done waiting")

            #Delete subscription
            self.deleteSubscription(username, tenant_id)

            #Delete tenant
            self.deleteTenant(tenant_id)

            #Delete user
            self.deleteUser(user_id)

        #Verify email notifications
        print("Waiting for emails to be sent .....")
        time.sleep(180)
        print("Done waiting")

        # client = MailosaurClient("XsGBz8E2AAjmekW")
        client = MailosaurClient(MAILOSAUS_API_KEY)

        # 2. Build search criteria to find the email you have sent
        criteria = SearchCriteria()
        criteria.sent_to = username
        criteria.subject = "INFO Alert"
        criteria.sent_from = "noreply-iotnms@cisco.com"
        criteria.body = body

        # 3. Wait for the message (by default only looks for messages received in the last hour)
        messages = client.messages.search(MAILOSAUR_SERVER_NAME, criteria)
        # 4. Assert that the email subject is what we expect
        self.assertEqual(NO_OF_NOTIFICATIONS, len(messages.items))

        for message in messages.items:
            client.messages.delete(message.id)

    def deleteSubscription(self, username, tenant_id):
        url = rainier_url + "audit/api/notification/subscriptions" + "?"
        # set params
        url += "service-name=" + SERVICE_NAME + "&" + "group-id=" + SERVICE_NAME + "-user-" + username
        headers = {
            "x-tenant-id": tenant_id,
            "Authorization": "Bearer " + service_token
        }
        self.call(url, "DELETE", headers, {}, True)
        print("Deleted subscription for service: " + SERVICE_NAME + ", group: " + SERVICE_NAME + "-user-" + username)

    def createSubscription(self, service_name, tenant_id, user_id, username):
        url = rainier_url + "audit/api/notification/subscriptions"
        payload = {
            "service-name": service_name,
            "groups": [
                {
                    "group-id": service_name + "-user-" + username,
                    "events": [
                        {
                            "event-name": service_name + "Asset",
                            "event-type": service_name + "down",
                            "severity": "INFO",
                            "email-template-source": "notification-service",
                            "email-template-name": "default",
                            "distribution-list": [
                                {
                                    "id": user_id,
                                    "email-pref": True,
                                    "sms-pref": False,
                                    "kind": "USER"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        headers = {
            "x-tenant-id": tenant_id,
            "Authorization": "Bearer "+service_token
        }
        self.call(url, "POST", headers, payload, True)

    def getServiceToken(self):
        url = rainier_url + "iam/auth/token"
        payload = {
            "client_id": "audit",
            "client_secret": "75afee93-5a3b-41b3-ab36-d35373a52da6",
            "grant_type": "client_credentials"
        }
        headers = {
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers, json=payload, verify=False)
        token = response.json()['access_token']
        return token

    def deleteUser(self, user_id):
        url = rainier_url + "iam/users/" + user_id
        self.call_iotadmin(url, "DELETE", {}, {})
        print("Deleted user id: " + user_id)

    def deleteTenant(self, tenant_id):
        url = rainier_url + "iam/tenants/" + tenant_id
        self.call_iotadmin(url, "DELETE", {}, {})
        print("Deleted tenant id: " + tenant_id)

    def createUser(self, username):
        payload = {
            "username": username,
            "firstName": username,
            "lastName": "user",
            "password": password,
            "email": username,
            "roles":
                [
                    {
                        "tenant_name": "Base Tenant",
                        "tenant_id": base_tenant_id,
                        "role_name": "sub_tenant_access",
                        "role_id": roleIdMap['sub_tenant_access']
                    }
                ]
        }
        response = self.call_iotadmin(rainier_url + "iam/users", "POST", {}, payload)
        return response.json()["user_uuid"]


    def createTenant(self, tenant_name, admins):
        # Create Tenant
        payload = {
            "name": tenant_name,
            "description": tenant_name,
            "parent_tenant_id": base_tenant_id,
            "admins": admins,
            "services": [],
            "notification_history": []
        }
        response = self.call_iotadmin(rainier_url + "iam/tenants", "POST", {}, payload)
        return response.json()["tenant_uuid"]


    def getBaseTenantId(self):
        response = self.call_iotadmin(rainier_url +"iam/tenants", "GET", headers={}, payload={})
        base_tenant_id = [tenant['id'] for tenant in response.json()['tenants'] if tenant['name'] == "Base Tenant"][0]
        print('Base Tenant ID: ' + base_tenant_id)
        return base_tenant_id

    def getRoleIdMap(self):
        response = self.call_iotadmin(rainier_url + "iam/roles", "GET", headers={}, payload={})
        return {role['name']:role['id'] for role in response.json()["roles"]}

    def call(self, url, method, headers, payload, service=False):
        global token
        global service_token
        headers["Content-Type"] = 'application/json'
        if "x-tenant-id" not in headers:
            headers["x-tenant-id"] = base_tenant_id
        response = requests.request(method, url, headers=headers, json=payload, verify=False)
        logging.debug("Calling url: "+url+", method: "+method)
        logging.debug("Response")
        logging.debug("-------------------------")
        logging.debug("status: "+str(response.status_code))
        logging.debug("body: "+str(response.text))
        logging.debug("--------------------------")
        if response.status_code != requests.codes.ok and response.status_code != requests.codes.created and response.status_code != requests.codes.unauthorized:
            print('ERROR on '+method+' to url: '+url)
            print('Status: '+str(response.status_code))
            print('Response: '+response.text)
            exit(1)
        if response.status_code == requests.codes.unauthorized and response.text == "Unauthorized":
            if service:
                service_token = self.getServiceToken()
                headers["Authorization"] = 'Bearer ' + service_token
            else:
                token = self.getToken()
                headers["Authorization"] = 'Bearer ' + token
            response = requests.request(method, url, headers=headers, json=payload, verify=False)
            logging.debug("Calling url: " + url + ", method: " + method)
            logging.debug("Response")
            logging.debug("-------------------------")
            logging.debug("status: " + str(response.status_code))
            logging.debug("body: " + str(response.text))
            logging.debug("--------------------------")
        return response

    def call_iotadmin(self, url, method, headers, payload):
        headers["Authorization"] = 'Bearer '+ token
        response = self.call(url, method, headers, payload)
        return response

    def getToken(self):
        url = rainier_url+"iam/auth/token"
        payload = {
            "grant-type": "client-credentials",
            "username": BASE_ADMIN_USERNAME,
            "password": password
        }
        headers = {
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers, json=payload, verify=False)
        token = response.json()['access_token']
        return token

if __name__ == '__main__':
    print('----------------------------------------------------')
    print('\t\tLoad Test Notifications')
    print('----------------------------------------------------')
    unittest.main()
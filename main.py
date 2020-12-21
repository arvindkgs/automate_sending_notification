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
from mailosaur.models import SearchCriteria, MailosaurException
from websocket import create_connection, WebSocketBadStatusException
import string
import random


from utils.commandwatch import CommandWatch

# Editable
SERVICE_NAME = "load-test"
SUBSCRPTION_GROUP_NAME = "load-test-e2e-audit-test"
NO_OF_SUBSCRIBERS = 1
NO_OF_NOTIFICATIONS = 1
ws_url = 'ws://localhost:8080'
rainier_url = "https://rainier.local"
tenant_name = "notification-test-tenant-1"
validate = True

# Non-Editable
TIMEOUT = 8 * NO_OF_NOTIFICATIONS * NO_OF_SUBSCRIBERS
password = "Rainier!20"
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
        self.mailosaur = MailosaurClient(MAILOSAUS_API_KEY)

    def test_notifications(self):
        global token
        token = self.getToken()
        global service_token
        service_token = self.getServiceToken()
        global base_tenant_id
        base_tenant_id = self.getBaseTenantId()
        global roleIdMap
        roleIdMap = self.getRoleIdMap()
        seconds_since_epoch = datetime.now().timestamp()
        user_ids = []
        usernames = []

        for i in range(NO_OF_SUBSCRIBERS):
            # Create User
            username = self.mailosaur.servers.generate_email_address(MAILOSAUR_SERVER_NAME)
            user_id = self.createUser(username)
            print("created user-id: " + user_id)
            user_ids.append(user_id)
            usernames.append(username)


        # Create tenant
        tenant_id = self.createTenant(tenant_name, usernames)
        print("created tenant-id: " + tenant_id)

        # Create subscription
        self.createSubscription(SERVICE_NAME, tenant_id, user_ids)

        body = "This is Sample Event one sent - " + str(seconds_since_epoch)
        execptionRaised = False
        try:
            # Generate and send notification
            ws = create_connection(ws_url + '/audit/ws/audit-ingest',
                                   header={"Authorization": "Bearer " + service_token},
                                   sslopt={"cert_reqs": ssl.CERT_NONE})
            # Start thread to listen to audit logs
            auditLogWatcher = CommandWatch(cmd='kubectl -n rainier logs -f --tail 0 rainier-audit-0',
                                           countdown=NO_OF_NOTIFICATIONS*NO_OF_SUBSCRIBERS,
                                           end_pattern=".*(Email Sent Successfully for:).*",
                                           start_pattern=".*(Size of notification queue is:)\s*\d+\s+(Size of event queue is:)\s*\d+")
            audit_run_task = auditLogWatcher.submit(TIMEOUT)
            print("Sending " + str(NO_OF_NOTIFICATIONS) + " notification, Body: " + body)
            msg = stomper.Frame()
            msg.cmd = 'SEND'
            msg.headers = {'destination': '/events/post', 'content_type': 'application/json', 'receipt': 'new-receipt'}

            msg.body = json.dumps({"tenant-id": tenant_id, "severity": "CRITICAL",
                                   "event-message": body, "event-name": SERVICE_NAME + "Asset",
                                   "time": int(round(time.time() * 1000)), "event-type": SERVICE_NAME + "down",
                                   "elementId": "oldvalue1",
                                   "neId": "newvalue1", "ne-kind": "userid6"})
            for i in range(NO_OF_NOTIFICATIONS):
                ws.send(msg.pack())
            ws.close()
        except Exception as err:
            print("-----Exception while trying to send notification via websocket-----")
            print(err)
            print(traceback.print_exc())
            print("-------------------------------------------------------------------")
            execptionRaised = True
            exit(1)
        finally:
            if not execptionRaised:
                # Wait till all notifications are read from queue
                print("Checking audit logs .....")
                runtime = audit_run_task.result()
                print("Notifications processing time taken: " + str(runtime) + " s")

            # Delete subscription
            self.deleteSubscription(tenant_id)

            # Delete tenant
            self.deleteTenant(tenant_id)

            # Delete user
            self.deleteUser(user_ids)

        if validate:
            # Verify email notifications
            print("Waiting for emails to be sent .....")
            time.sleep(10)
            print("Done waiting")

            for user in usernames:
                # 2. Build search criteria to find the email you have sent
                print("Checking for user: "+user)
                criteria = SearchCriteria()
                criteria.sent_to = user
                criteria.subject = "INFO Alert"
                criteria.sent_from = "noreply-iotnms@cisco.com"
                criteria.body = body
                try:
                    # 3. Wait for the message (by default only looks for messages received in the last hour)
                    messages = self.mailosaur.messages.search(MAILOSAUR_SERVER_NAME, criteria)
                    message_list = {}
                    if len(messages.items) > 0:
                        for message in messages.items:
                            if message.id not in message_list:
                                message_list[message.id]=message
                    t_end = time.time() + 60 * 2  # wait for 2 mins
                    i = 1
                    while time.time() < t_end and len(messages.items) < NO_OF_NOTIFICATIONS:
                        time.sleep(10 * i)
                        messages = self.mailosaur.messages.search(MAILOSAUR_SERVER_NAME, criteria)
                        if len(messages.items) > 0:
                            for message in messages.items:
                                if message.id not in message_list:
                                    message_list[message.id] = message
                except MailosaurException as err:
                    print(err.error_type)
                    print(err.message)
                    print("Response code: "+err.http_status_code+", body: "+err.http_response_body)
                    print(traceback.print_exc())

                # 4. Assert that the email subject is what we expect
                self.assertEqual(NO_OF_NOTIFICATIONS, len(messages.items))

                for key in message_list:
                    message = self.mailosaur.messages.get_by_id(key)
                    print("To: "+",".join(str(p.email) for p in message.to))
                    print("Bcc: "+",".join(str(p.email) for p in message.bcc))
                    print("Text Content: " + str(message.text.body))
                    print("HTML Content: " + str(message.html.body))

                for message in messages.items:
                    self.mailosaur.messages.delete(message.id)

    def genereate_random_strings(self):
        return ''.join(random.choices(string.ascii_uppercase +
                                     string.digits, k=7))


    def deleteSubscription(self, tenant_id):
        url = rainier_url + "/audit/api/notification/subscriptions" + "?"
        # set params
        url += "service-name=" + SERVICE_NAME + "&" + "group-id=" + SUBSCRPTION_GROUP_NAME
        headers = {
            "x-tenant-id": tenant_id,
            "Authorization": "Bearer " + service_token
        }
        self.call(url, "DELETE", headers, {}, True)
        print("Deleted subscription for service: " + SERVICE_NAME + ", group: " + SUBSCRPTION_GROUP_NAME)

    def createSubscription(self, service_name, tenant_id, users):
        url = rainier_url + "/audit/api/notification/subscriptions"
        subscribers_list = []
        for user in users:
            distributer = {
                "id": user,
                "email-pref": True,
                "sms-pref": False,
                "kind": "USER"
            }
            subscribers_list.append(distributer)
        payload = {
            "service-name": service_name,
            "groups": [
                {
                    "group-id": SUBSCRPTION_GROUP_NAME,
                    "events": [
                        {
                            "event-name": service_name + "Asset",
                            "event-type": service_name + "down",
                            "severity": "INFO",
                            "email-template-source": "notification-service",
                            "email-template-name": "default",
                            "distribution-list": subscribers_list
                        }
                    ]
                }
            ]
        }
        headers = {
            "x-tenant-id": tenant_id,
            "Authorization": "Bearer " + service_token
        }
        self.call(url, "POST", headers, payload, True)

    def getServiceToken(self):
        url = rainier_url + "/iam/auth/token"
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

    def deleteUser(self, user_ids):
        for user_id in user_ids:
            url = rainier_url + "/iam/users/" + user_id
            self.call_iotadmin(url, "DELETE", {}, {})
            print("Deleted user id: " + user_id)

    def deleteTenant(self, tenant_id):
        url = rainier_url + "/iam/tenants/" + tenant_id
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
        response = self.call_iotadmin(rainier_url + "/iam/users", "POST", {}, payload)
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
        response = self.call_iotadmin(rainier_url + "/iam/tenants", "POST", {}, payload)
        return response.json()["tenant_uuid"]

    def getBaseTenantId(self):
        response = self.call_iotadmin(rainier_url + "/iam/tenants", "GET", headers={}, payload={})
        base_tenant_id = [tenant['id'] for tenant in response.json()['tenants'] if tenant['name'] == "Base Tenant"][0]
        print('Base Tenant ID: ' + base_tenant_id)
        return base_tenant_id

    def getRoleIdMap(self):
        response = self.call_iotadmin(rainier_url + "/iam/roles", "GET", headers={}, payload={})
        return {role['name']: role['id'] for role in response.json()["roles"]}

    def call(self, url, method, headers, payload, service=False):
        global token
        global service_token
        headers["Content-Type"] = 'application/json'
        if "x-tenant-id" not in headers:
            headers["x-tenant-id"] = base_tenant_id
        response = requests.request(method, url, headers=headers, json=payload, verify=False)
        logging.debug("Calling url: " + url + ", method: " + method)
        logging.debug("Response")
        logging.debug("-------------------------")
        logging.debug("status: " + str(response.status_code))
        logging.debug("body: " + str(response.text))
        logging.debug("--------------------------")
        if response.status_code != requests.codes.ok and response.status_code != requests.codes.created and response.status_code != requests.codes.unauthorized:
            print('ERROR on ' + method + ' to url: ' + url)
            print('Status: ' + str(response.status_code))
            print('Response: ' + response.text)
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
        headers["Authorization"] = 'Bearer ' + token
        response = self.call(url, method, headers, payload)
        return response

    def getToken(self):
        url = rainier_url + "/iam/auth/token"
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

from typing import Dict, List
import requests
import json

from pydantic import BaseModel

# Constants
REALM_MANAGEMENT = "realm-management"


def get_keycloak_access_token(
    base_url: str, admin_username: str, admin_password: str
) -> str | None:
    try:
        url = f"{base_url}/realms/master/protocol/openid-connect/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": "admin-cli",
            "username": admin_username,
            "password": admin_password,
            "grant_type": "password",
        }

        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # If the request was successful
        # print("Response content:", response.text)  # or response.json() if the response is JSON

        # Extract access token from token request
        return response.json()["access_token"]

    except requests.exceptions.HTTPError as e:
        # Handle HTTP errors (e.g., 404 Not Found, 500 Internal Server Error)
        print(f"HTTP error occurred: {e}")
        print(f"Error details: {response.text}")

    except KeyError as e:
        print(f"Cannot obtain access token")
        print(f"Error details: {response.text}")


class ProtocolMapper(BaseModel):
    name: str
    protocol: str | None
    protocolMapper: str | None
    config: Dict[str, str]


class ClientScope(BaseModel):
    name: str
    protocol: str | None
    protocolMappers: List[ProtocolMapper]


def get_bearer_token(access_token: str) -> str:
    return f"Bearer {access_token}"


def create_keycloak_client_scope(
    client_scope: ClientScope, base_url: str, realm: str, access_token: str
):
    try:
        url = f"{base_url}/admin/realms/{realm}/client-scopes"
        headers = {
            "Content-Type": "application/json",
            "Authorization": get_bearer_token(access_token),
        }

        response = requests.post(url, headers=headers, data=json.dumps(client_scope))
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

    except requests.exceptions.HTTPError as e:
        # Handle HTTP errors (e.g., 404 Not Found, 500 Internal Server Error)
        print(f"HTTP error occurred: {e}")
        print(f"Error details: {response.text}")


class Client(BaseModel):
    clientId: str
    clientAuthenticatorType: str | None
    standardFlowEnabled: bool | None
    directAccessGrantsEnabled: bool | None
    protocol: str | None
    attributes: Dict[str, str]
    fullScopeAllowed: bool | None
    optionalClientScopes: List[str]


def create_keycloak_client(
    client: Client, base_url: str, realm: str, access_token: str
):
    try:
        url = f"{base_url}/admin/realms/{realm}/clients"
        headers = {
            "Content-Type": "application/json",
            "Authorization": get_bearer_token(access_token),
        }

        response = requests.post(url, headers=headers, data=json.dumps(client))
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        # # If the request was successful
        # print("Response content:", response.text)  # or response.json() if the response is JSON

    except requests.exceptions.HTTPError as e:
        # Handle HTTP errors (e.g., 404 Not Found, 500 Internal Server Error)
        print(f"HTTP error occurred: {e}")
        print(f"Error details: {response.text}")

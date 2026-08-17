#!/usr/bin/env python

#  Copyright (c) 2022 DXC Technology. All rights reserved.

import argparse
import os
import requests
import string
import sys
import yaml


class ExtendedTemplate(string.Template):
    """
    Template with customized idpattern since we also want to allow ".", "-" in identifier
    """
    idpattern = r'[_a-z][_a-z0-9.\-]*'


def read_import_file(work_dir, file_name, params):
    """
    Reads import file
    """
    yml_path = os.path.join(work_dir, file_name)
    if os.path.isfile(yml_path):
        with open(yml_path, "r") as yml_file:
            yml_template = ExtendedTemplate(yml_file.read())
            yml_content = yml_template.safe_substitute(params)
            return yaml.safe_load(yml_content)
    else:
        return None


def login(url, username, password, ca):
    """
    Login into Keystone API
    """
    sys.stdout.write("Login user\n")

    api_url = url + "/auth/tokens"
    login_body = {
        "auth": {
            "identity": {
                "methods": [
                    "password"
                ],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {
                            "name": "Default"
                        },
                        "password": password
                    }
                }
            },
            "scope": {
                "project": {
                    "name": "admin",
                    "domain": {
                        "name": "Default"
                    }
                }
            }
        }
    }
    response = requests.post(api_url, json=login_body, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Login error {0}\n".format(response.status_code))
        raise
    return response.headers['X-Subject-Token']


def load_roles(url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/roles", headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get roles error {0}\n".format(response.status_code))
        raise
    role_list = response.json()['roles']
    sys.stdout.write("Loaded {0} existing roles\n".format(len(role_list)))
    result = {}
    for role in role_list:
        result[role['name']] = role
    return result


def load_implied_roles(url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/role_inferences", headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get role inferences error {0}\n".format(response.status_code))
        raise
    role_list = response.json()['role_inferences']
    sys.stdout.write("Loaded {0} existing roles implications\n".format(len(role_list)))
    result = {}
    for role in role_list:
        implied = []
        for inherited in role['implies']:
            implied.append(inherited['name'])
        result[role['prior_role']['name']] = implied
    return result


def import_role(role, roles, url, token, ca):
    role_name = role['role']

    if role_name not in roles:
        new_role = create_role(role_name, url, token, ca)
        roles[role_name] = new_role

    return


def import_role_inheritance(role, roles, implied_roles, url, token, ca):
    role_name = role['role']

    if 'implies' in role:
        for implied_role in role['implies']:
            if role_name not in implied_roles or implied_role not in implied_roles[role_name]:
                create_role_implication(role_name, implied_role, roles, url, token, ca)
                if role_name not in implied_roles:
                    implied_roles[role_name] = [implied_role]
                else:
                    implied_roles[role_name].append(implied_role)

    if 'not_implies' in role:
        for implied_role in role['not_implies']:
            if role_name in implied_roles and implied_role in implied_roles[role_name]:
                delete_role_implication(role_name, implied_role, roles, url, token, ca)
                if role_name in implied_roles:
                    implied_roles[role_name].remove(implied_role)

    return


def create_role(role_name, url, token, ca):
    sys.stdout.write("Create role {0}\n".format(role_name))
    headers = {"X-Auth-Token": token}
    api_url = url + "/roles"
    role_body = {
        "role": {
            "name": role_name
        }
    }
    response = requests.post(api_url, json=role_body, headers=headers, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Create role error {0}\n".format(response.status_code))
        raise
    return response.json()['role']


def create_role_implication(parent_role_name, inherited_role_name, roles, url, token, ca):
    sys.stdout.write("Create role implication {0} -> {1}\n".format(parent_role_name, inherited_role_name))
    headers = {"X-Auth-Token": token}
    parent_role_id = roles[parent_role_name]['id']
    inherited_role_id = roles[inherited_role_name]['id']
    api_url = url + "/roles/" + parent_role_id + "/implies/" + inherited_role_id
    response = requests.put(api_url, headers=headers, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Create role implication error {0}\n".format(response.status_code))
        raise
    return


def delete_role_implication(parent_role_name, inherited_role_name, roles, url, token, ca):
    sys.stdout.write("Delete role implication {0} -> {1}\n".format(parent_role_name, inherited_role_name))
    headers = {"X-Auth-Token": token}
    parent_role_id = roles[parent_role_name]['id']
    inherited_role_id = roles[inherited_role_name]['id']
    api_url = url + "/roles/" + parent_role_id + "/implies/" + inherited_role_id
    response = requests.delete(api_url, headers=headers, verify=ca)
    if response.status_code != 204:
        sys.stdout.write("Delete role implication error {0}\n".format(response.status_code))
        raise
    return


def import_domain(domain, url, token, ca):
    domain_obj = find_domain(domain['domain'], url, token, ca)
    if domain_obj is None:
        domain_obj = create_domain(domain['domain'], domain['description'], domain.get('customer_id'), url, token, ca)
    else:
        sys.stdout.write("Using existing domain {0}\n".format(domain['domain']))
    return domain_obj


def find_domain(domain_name, url, token, ca):
    headers = {"X-Auth-Token": token}
    api_url = url + "/domains?name=" + domain_name
    response = requests.get(api_url, headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Find domain error {0}\n".format(response.status_code))
        raise
    domains = response.json()['domains']
    if len(domains) > 0:
        return domains[0]
    else:
        return None


def create_domain(domain_name, description, customer_id, url, token, ca):
    sys.stdout.write("Create domain {0}\n".format(domain_name))
    headers = {"X-Auth-Token": token}
    api_url = url + "/domains"
    domain_body = {
        "domain": {
            "name": domain_name,
            "description": description,
            "enabled": True
        }
    }
    if customer_id is not None:
        domain_body['domain']['vpc_customer_id'] = customer_id

    response = requests.post(api_url, json=domain_body, headers=headers, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Create domain error {0}\n".format(response.status_code))
        raise
    return response.json()['domain']


def load_users(domain_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/users?domain_id=" + domain_id, headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get users error {0}\n".format(response.status_code))
        raise
    user_list = response.json()['users']
    sys.stdout.write("Loaded {0} existing users\n".format(len(user_list)))
    result = {}
    for user in user_list:
        result[user['name']] = user
    return result


def load_groups(domain_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/groups?domain_id=" + domain_id, headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get groups error {0}\n".format( response.status_code))
        raise
    group_list = response.json()['groups']
    sys.stdout.write("Loaded {0} existing groups\n".format(len(group_list)))
    result = {}
    for group in group_list:
        result[group['name']] = group
    return result


def import_user(user, users, roles, domain_id, url, token, ca):
    user_name = user['user']

    if user_name not in users:
        new_user = create_user(user_name, domain_id, user['password'], url, token, ca)
        users[user_name] = new_user

    user_id = users[user_name]['id']
    user_roles = load_user_roles(user_id, domain_id, url, token, ca)
    if 'roles' in user:
        for role in user['roles']:
            if role not in user_roles:
                assign_role_to_user(user_id, roles[role]['id'], domain_id, url, token, ca)
    return


def create_user(user_name, domain_id, password, url, token, ca):
    sys.stdout.write("Create user {0}\n".format(user_name))
    headers = {"X-Auth-Token": token}
    api_url = url + "/users"
    user_body = {
        "user": {
            "name": user_name,
            "password": password,
            "domain_id": domain_id,
            "options": {
                "ignore_change_password_upon_first_use": True
            }
        }
    }
    response = requests.post(api_url, json=user_body, headers=headers, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Create user error {0} {1}\n".format(response.status_code, response.text))
        raise

    response2 = requests.patch(api_url+"/"+response.json()['user']['id'], json=user_body, headers=headers, verify=ca)
    if response2.status_code != 200:
        sys.stdout.write("Create user error {0} {1}\n".format(response2.status_code, response2.text))
        raise

    return response.json()['user']


def load_user_roles(user_id, domain_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/domains/"+domain_id+"/users/"+user_id+"/roles", headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get user roles error {0}\n".format(response.status_code))
        raise
    role_list = response.json()['roles']
    result = []
    for role in role_list:
        result.append(role['name'])
    return result


def assign_role_to_user(user_id, role_id, domain_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.put(url + "/domains/"+domain_id+"/users/"+user_id+"/roles/"+role_id, headers=headers, verify=ca)
    if response.status_code != 204:
        sys.stdout.write("Assign user roles error {0}\n".format(response.status_code))
        raise


def import_group(group, groups, users, domain_id, url, token, ca):
    group_name = group['group']
    if group_name not in groups:
        new_group = create_group(group_name, domain_id, url, token, ca)
        groups[group_name] = new_group

    group_id = groups[group_name]['id']
    sys.stdout.write("Group id {0}\n".format(group_id))
    group_users = load_group_users(group_id, url, token, ca)
    sys.stdout.write("Group users {0}\n".format(len(group_users)))
    if 'users' in group:
        for user in group['users']:
            sys.stdout.write("Check user {0}\n".format(user))
            if user not in group_users:
                sys.stdout.write("Assign user {0}\n".format(user))
                assign_user_to_group(users[user]['id'], group_id, url, token, ca)
    return


def create_group(group_name, domain_id, url, token, ca):
    sys.stdout.write("Create group {0}\n".format(group_name))
    headers = {"X-Auth-Token": token}
    api_url = url + "/groups"
    group_body = {
        "group": {
            "name": group_name,
            "domain_id": domain_id
        }
    }
    response = requests.post(api_url, json=group_body, headers=headers, verify=ca)
    if response.status_code != 201:
        sys.stdout.write("Create group error {0}\n".format(response.status_code))
        raise

    return response.json()['group']


def load_group_users(group_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.get(url + "/groups/"+group_id+"/users", headers=headers, verify=ca)
    if response.status_code != 200:
        sys.stdout.write("Get group users error {0}\n".format(response.status_code))
        raise
    user_list = response.json()['users']
    result = []
    for user in user_list:
        result.append(user['name'])
    return result


def assign_user_to_group(user_id, group_id, url, token, ca):
    headers = {"X-Auth-Token": token}
    response = requests.put(url + "/groups/"+group_id+"/users/"+user_id, headers=headers, verify=ca)
    if response.status_code != 204:
        sys.stdout.write("Assign group users error {0}\n".format(response.status_code))
        raise


def build_params(args):
    params = {}
    if args.extraParams:
        for entry in args.extraParams:
            s = entry.split(',')
            params[s[0]] = s[1]
    return params


def keystone_import(source_dir, args):
    params = build_params(args)
    import_file = read_import_file(source_dir, args.importFile, params)
    if import_file is None:
        sys.stdout.write("Import file not found\n")
        return
    token = login(args.keystoneUrl, args.keystoneUser, args.keystonePassword, args.caCert)

    roles = load_roles(args.keystoneUrl, token, args.caCert)
    implied_roles = load_implied_roles(args.keystoneUrl, token, args.caCert)
    domain_id = None

    for entry in import_file:
        if 'role' in entry:
            import_role(entry, roles, args.keystoneUrl, token, args.caCert)
        elif 'domain' in entry:
            domain_id = import_domain(entry, args.keystoneUrl, token, args.caCert)['id']

    for entry in import_file:
        if 'implies' in entry or 'not_implies' in entry:
            import_role_inheritance(entry, roles, implied_roles, args.keystoneUrl, token, args.caCert)

    if domain_id is not None:
        users = load_users(domain_id, args.keystoneUrl, token, args.caCert)
        groups = load_groups(domain_id, args.keystoneUrl, token, args.caCert)

        for entry in import_file:
            if 'user' in entry:
                import_user(entry, users, roles, domain_id, args.keystoneUrl, token, args.caCert)
            elif 'group' in entry:
                import_group(entry, groups, users, domain_id, args.keystoneUrl, token, args.caCert)

    sys.stdout.write("Finished\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Keystone users and roles")
    parser.add_argument("-i", "--importFile", metavar="FILE", dest="importFile",
                        help="YML file containing roles or users to import", required=True)
    parser.add_argument("-k", "--keystoneUrl", metavar="URL", dest="keystoneUrl",
                        help="Keystone API URL e.g. https://server:35357/api/idm/v3", required=True)
    parser.add_argument("-u", "--username", metavar="USERNAME", dest="keystoneUser", help="Keystone admin username",
                        required=True)
    parser.add_argument("-p", "--password", metavar="PASSWORD", dest="keystonePassword", help="Keystone admin password",
                        required=True)
    parser.add_argument("-c", "--CACert", metavar="CERT", dest="caCert", help="CA certificate", required=True)
    parser.add_argument("-e", "--extraParams", metavar="PARAMS", dest="extraParams", nargs="+",
                        help="Additional parameters used for replacement in input file, in format key1,value1 key2,value2")
    args = parser.parse_args()  # exits if there is argument error

    keystone_import(os.getcwd(), args)
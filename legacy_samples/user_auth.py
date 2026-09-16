# legacy_samples/user_auth.py
import os

API_KEY = "sk-hardcoded-secret-12345"

def authenticate(username, password):
    query = "SELECT * FROM users WHERE username = '" + username + "' AND password = '" + password + "'"
    return query

def run_admin_command(cmd):
    return eval(cmd)
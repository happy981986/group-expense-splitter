import csv
import datetime
import pytz
import requests
import subprocess
import urllib.parse

from flask import redirect, render_template, request, session 
from functools import wraps


def apology(message, code=400):
    """Render message as an apology to user."""
    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [("-", "--"), ("_", "__"), ("?", "~q"),
                         ("%", "~p"), ("#", "~h"), ("/", "~s"), ('"', "''")]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

def calculate_settlements(balances):
    """
    Takes a dictionary of {user_id: net_balance}
    Returns a list of dicts: [{'from_user': id, 'to_user': id, 'amount': float}]
    """
    debtors = []   # (user_id, amount_owed_as_positive)
    creditors = [] # (user_id, amount_due)

    for user_id, amount in balances.items():
        amount = round(amount, 2)
        if amount < -0.01:
            debtors.append({'user_id': user_id, 'amount': abs(amount)})
        elif amount > 0.01:
            creditors.append({'user_id': user_id, 'amount': amount})

    debtors.sort(key=lambda x: x['amount'], reverse=True)
    creditors.sort(key=lambda x: x['amount'], reverse=True)

    transactions = []
    i, j = 0, 0

    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]

        settle_amount = min(debtor['amount'], creditor['amount'])

        if settle_amount > 0:
            transactions.append({
                'from_user': debtor['user_id'],
                'to_user': creditor['user_id'],
                'amount': round(settle_amount, 2)
            })

        debtor['amount'] -= settle_amount
        creditor['amount'] -= settle_amount

        if round(debtor['amount'], 2) == 0:
            i += 1
        if round(creditor['amount'], 2) == 0:
            j += 1

    return transactions

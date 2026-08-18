import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session,send_from_directory
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)



# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///splitter.db")


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js")

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response




@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    if request.method == "POST":
        if not request.form.get("username"):
            return apology("must provide username", 403)
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["id"]
        return redirect("/")
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            return apology("must fill all fields", 400)
        if password != confirmation:
            return apology("passwords do not match", 400)

        hash_pw = generate_password_hash(password)
        try:
            db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, hash_pw)
        except ValueError:
            return apology("username already exists", 400)

        return redirect("/login")
    else:
        return render_template("register.html")


@app.route("/")
@login_required
def index():
    # 1. Groups the logged-in user IS a member of
    my_groups = db.execute(
        "SELECT groups.id, groups.name FROM groups "
        "JOIN group_members ON groups.id = group_members.group_id "
        "WHERE group_members.user_id = ?",
        session["user_id"]
    )

    # 2. Groups the logged-in user IS NOT a member of
    other_groups = db.execute(
        "SELECT id, name FROM groups WHERE id NOT IN ("
        "  SELECT group_id FROM group_members WHERE user_id = ?"
        ")",
        session["user_id"]
    )

    return render_template("index.html", my_groups=my_groups, other_groups=other_groups)


@app.route("/create_group", methods=["GET", "POST"])
@login_required
def create_group():
    if request.method == "POST":
        group_name = request.form.get("name")
        if not group_name:
            return apology("must provide group name", 400)

        # Insert new group into database
        group_id = db.execute("INSERT INTO groups (name) VALUES(?)", group_name)

        # Automatically add the creator as the first member
        db.execute("INSERT INTO group_members (group_id, user_id) VALUES(?, ?)", group_id, session["user_id"])

        flash(f"Group '{group_name}' created successfully!")
        return redirect("/")
    else:
        return render_template("create_group.html")


@app.route("/group/<int:group_id>", methods=["GET"])
@login_required
def group_detail(group_id):
    """View details, members, expenses, and net balances of a group"""

    # 1. Check membership
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        group_id, session["user_id"]
    )
    if not membership:
        return apology("group not found or access denied", 403)

    # 2. Fetch group details
    group = db.execute("SELECT * FROM groups WHERE id = ?", group_id)
    if not group:
        return apology("group not found", 404)

    # 3. Fetch members
    members = db.execute(
        "SELECT users.id, users.username FROM users "
        "JOIN group_members ON users.id = group_members.user_id "
        "WHERE group_members.group_id = ?",
        group_id
    )

    # 4. Fetch non-members for dropdown
    non_members = db.execute(
        "SELECT id, username FROM users WHERE id NOT IN ("
        "  SELECT user_id FROM group_members WHERE group_id = ?"
        ")",
        group_id
    )

    # 5. Fetch expense history
    expenses = db.execute(
        "SELECT expenses.id, expenses.description, expenses.amount, expenses.created_at, "
        "users.username AS payer_name "
        "FROM expenses "
        "JOIN users ON expenses.payer_id = users.id "
        "WHERE expenses.group_id = ? "
        "ORDER BY expenses.created_at DESC",
        group_id
    )

    # 6. Calculate Net Balances for each member
    balances = []
    for member in members:
        user_id = member["id"]

        # Total paid by this member in this group
        paid_res = db.execute(
            "SELECT SUM(amount) AS total FROM expenses WHERE group_id = ? AND payer_id = ?",
            group_id, user_id
        )
        total_paid = paid_res[0]["total"] or 0.0

        # Total owed by this member across all expenses in this group
        owed_res = db.execute(
            "SELECT SUM(expense_splits.amount_owed) AS total FROM expense_splits "
            "JOIN expenses ON expense_splits.expense_id = expenses.id "
            "WHERE expenses.group_id = ? AND expense_splits.user_id = ?",
            group_id, user_id
        )
        total_owed = owed_res[0]["total"] or 0.0

        net = round(total_paid - total_owed, 2)
        balances.append({
            "username": member["username"],
            "paid": total_paid,
            "owed": total_owed,
            "net": net
        })

    return render_template(
        "group.html",
        group=group[0],
        members=members,
        non_members=non_members,
        expenses=expenses,
        balances=balances
    )

@app.route("/add_member/<int:group_id>", methods=["POST"])
@login_required
def add_member(group_id):
    """Add a registered user to a group manually"""
    new_user_id = request.form.get("user_id")
    if not new_user_id:
        return apology("must select a user", 400)

    # Ensure logged-in user is part of the group
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        group_id, session["user_id"]
    )
    if not membership:
        return apology("access denied", 403)

    db.execute(
        "INSERT INTO group_members (group_id, user_id) VALUES(?, ?)",
        group_id, new_user_id
    )

    flash("Member added successfully!")
    return redirect(f"/group/{group_id}")

@app.route("/join_group/<int:group_id>", methods=["POST"])
@login_required
def join_group(group_id):
    """Allow user to join an existing group"""

    # 1. Verify group exists
    group = db.execute("SELECT * FROM groups WHERE id = ?", group_id)
    if not group:
        return apology("group not found", 404)

    # 2. Check if user is already a member
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        group_id, session["user_id"]
    )
    if membership:
        flash("You are already in this group!")
        return redirect(f"/group/{group_id}")

    # 3. Insert membership record
    db.execute(
        "INSERT INTO group_members (group_id, user_id) VALUES(?, ?)",
        group_id, session["user_id"]
    )

    flash(f"Joined '{group[0]['name']}' successfully!")
    return redirect(f"/group/{group_id}")

@app.route("/add_expense/<int:group_id>", methods=["GET", "POST"])
@login_required
def add_expense(group_id):
    """Add a new expense to a group and split it equally among members"""

    # 1. Ensure logged-in user belongs to this group
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        group_id, session["user_id"]
    )
    if not membership:
        return apology("access denied", 403)

    if request.method == "POST":
        description = request.form.get("description")
        amount_str = request.form.get("amount")

        # Validate inputs
        if not description or not amount_str:
            return apology("must provide description and amount", 400)

        try:
            amount = float(amount_str)
            if amount <= 0:
                return apology("amount must be positive", 400)
        except ValueError:
            return apology("invalid amount", 400)

        # 2. Get all members in this group to divide the cost
        members = db.execute(
            "SELECT user_id FROM group_members WHERE group_id = ?",
            group_id
        )
        if not members:
            return apology("no members in group", 400)

        # 3. Insert into expenses table (Payer = current logged-in user)
        expense_id = db.execute(
            "INSERT INTO expenses (group_id, payer_id, description, amount) VALUES(?, ?, ?, ?)",
            group_id, session["user_id"], description, amount
        )

        # 4. Calculate split amount per member
        split_amount = round(amount / len(members), 2)

        # 5. Insert split record for every member in the group
        for member in members:
            db.execute(
                "INSERT INTO expense_splits (expense_id, user_id, amount_owed) VALUES(?, ?, ?)",
                expense_id, member["user_id"], split_amount
            )

        flash("Expense added successfully!")
        return redirect(f"/group/{group_id}")

    else:
        # GET request: fetch group details for the form
        group = db.execute("SELECT * FROM groups WHERE id = ?", group_id)
        return render_template("add_expense.html", group=group[0])

@app.route("/group/<int:group_id>/settle", methods=["POST"])
@login_required
def settle_up(group_id):
    """Record a settlement payment between two members using existing tables"""

    # 1. Verify group membership
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        group_id, session["user_id"]
    )
    if not membership:
        return apology("access denied", 403)

    payer_id = request.form.get("payer_id")
    payee_id = request.form.get("payee_id")
    amount_str = request.form.get("amount")

    if not payer_id or not payee_id or not amount_str:
        flash("Invalid settlement details.", "error")
        return redirect(f"/group/{group_id}")

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash("Amount must be greater than 0.", "error")
            return redirect(f"/group/{group_id}")
    except ValueError:
        flash("Invalid amount entered.", "error")
        return redirect(f"/group/{group_id}")

    # Fetch payee username for description
    payee = db.execute("SELECT username FROM users WHERE id = ?", payee_id)
    if not payee:
        return apology("invalid payee", 400)

    description = f"Settlement payment to {payee[0]['username']}"

    # 2. Insert into expenses (Payer increases their total paid)
    expense_id = db.execute(
        "INSERT INTO expenses (group_id, payer_id, description, amount) VALUES(?, ?, ?, ?)",
        group_id, payer_id, description, amount
    )

    # 3. Insert into expense_splits (Payee absorbs the full split share)
    db.execute(
        "INSERT INTO expense_splits (expense_id, user_id, amount_owed) VALUES(?, ?, ?)",
        expense_id, payee_id, amount
    )

    flash("Settlement successfully recorded!")
    return redirect(f"/group/{group_id}")

"""Role-based access control.

Every portal module has <module>.view / .create / .edit / .delete / .approve / .direct
(direct = written to QuickBooks without approval). Roles live in the database and are edited
on the Roles page; the defaults below are only seeded once.
"""

from .qb.registry import MODULES, module_permissions

SYNC_RUN = "sync.run"
USERS_MANAGE = "users.manage"
AUDIT_VIEW = "audit.view"

ADMIN_PERMS = [SYNC_RUN, USERS_MANAGE, AUDIT_VIEW]
ALL = module_permissions() + ADMIN_PERMS


def _module(m: str, *actions: str) -> list[str]:
    return [f"{m}.{a}" for a in actions]


ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ALL,
    "accountant": module_permissions() + [SYNC_RUN],
    "sales": _module("sales", "view", "create", "edit") + _module("lists", "view") + ["reports.view"],
    "purchasing": _module("purchasing", "view", "create", "edit") + _module("lists", "view")
                  + _module("inventory", "view"),
    "viewer": [f"{m}.view" for m in MODULES if m != "reports"],
}

LABELS = {SYNC_RUN: "Run QuickBooks sync", USERS_MANAGE: "Manage users & roles", AUDIT_VIEW: "View audit log",
          "reports.view": "Run QuickBooks reports"}
ACTION_LABELS = {"view": "View", "create": "Create", "edit": "Edit", "delete": "Delete / void",
                 "approve": "Approve changes", "direct": "Write without approval"}


def catalog() -> list[dict]:
    """Permissions grouped for the role editor."""
    groups = []
    for m, label in MODULES.items():
        if m == "reports":
            continue
        groups.append({"group": label, "permissions": [{"key": f"{m}.{a}", "label": ACTION_LABELS[a]}
                                                       for a in ACTION_LABELS]})
    groups.append({"group": MODULES["reports"], "permissions": [{"key": "reports.view", "label": LABELS["reports.view"]}]})
    groups.append({"group": "Administration", "permissions": [{"key": p, "label": LABELS[p]} for p in ADMIN_PERMS]})
    return groups

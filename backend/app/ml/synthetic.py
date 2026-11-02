"""Synthetic ITSM history. Contains no real or proprietary data.

The goal is data that is hard in the ways real tickets are hard, because clean templates
would produce a near-perfect and meaningless score:

* topics that overlap across categories, plus vague tickets that carry little signal
* human labelling mistakes, typos, signatures and repeated monitoring alerts
* a queueing simulation in which SLA outcomes depend on staffing, backlog and time of day,
  plus random effects no model can see, so breach prediction is genuinely uncertain
"""

import heapq
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.core.enums import Category, Channel, Level, compute_priority

SLA_TARGET_MINUTES = {"P1": 240, "P2": 480, "P3": 1440, "P4": 4320}

TEAM_STAFF = {
    "Network Operations": 4,
    "Identity & Access": 3,
    "End User Computing": 5,
    "Application Support": 5,
    "Database Administration": 2,
    "Cloud Platform": 3,
    "Security Operations": 3,
}

APPS = ["Orion ERP", "HelixCRM", "PayrollHub", "Atlas Portal", "TimeTrack", "DocuVault", "Nimbus BI"]
SITES = ["Pune campus", "Noida office", "Bengaluru hub", "Hyderabad site", "Chennai office", "Mumbai branch"]
DEVICES = ["Latitude 7440", "ThinkPad T14", "EliteBook 840", "MacBook Pro", "Surface Laptop"]
SERVICES = ["orders-api", "billing-worker", "auth-gateway", "report-engine", "search-indexer"]
DBS = ["orders_prod", "finance_dw", "crm_primary", "hr_replica", "inventory_db"]
CODES = ["0x80070005", "ERR_CONN_RESET", "ORA-12541", "HTTP 503", "SQLSTATE 53300", "AADSTS50126", "KB5034441"]


@dataclass(frozen=True)
class Topic:
    key: str
    category: Category
    teams: tuple[tuple[str, float], ...]
    hours: float
    high_impact_rate: float
    phrases: tuple[str, ...]


def _t(key, category, teams, hours, high, *phrases) -> Topic:
    return Topic(key, category, teams, hours, high, phrases)


_NET = (("Network Operations", 1.0),)
_NET_EUC = (("Network Operations", 0.6), ("End User Computing", 0.4))
_IAM = (("Identity & Access", 1.0),)
_IAM_NET = (("Identity & Access", 0.65), ("Network Operations", 0.35))
_EUC = (("End User Computing", 1.0),)
_APP = (("Application Support", 1.0),)
_APP_EUC = (("Application Support", 0.55), ("End User Computing", 0.45))
_DBA = (("Database Administration", 1.0),)
_DBA_APP = (("Database Administration", 0.7), ("Application Support", 0.3))
_CLOUD = (("Cloud Platform", 1.0),)
_CLOUD_APP = (("Cloud Platform", 0.7), ("Application Support", 0.3))
_SEC = (("Security Operations", 1.0),)
_SEC_IAM = (("Security Operations", 0.75), ("Identity & Access", 0.25))

TOPICS: tuple[Topic, ...] = (
    _t(
        "vpn_drop",
        Category.NETWORK,
        _NET,
        5,
        0.2,
        "VPN keeps disconnecting every few minutes from {site}",
        "tunnel drops when I work from home, reconnect loops forever",
        "Remote connection unstable, session falls over during calls",
    ),
    _t(
        "wifi",
        Category.NETWORK,
        _NET_EUC,
        4,
        0.1,
        "Wireless at {site} is very slow on the third floor",
        "wifi access point keeps dropping laptops near the meeting rooms",
        "Cannot join the corporate SSID at {site}, signal bars are low",
    ),
    _t(
        "dns",
        Category.NETWORK,
        _NET,
        7,
        0.3,
        "Internal sites do not resolve, name lookup fails for {service}",
        "getting {code} when opening intranet pages, hostname not found",
        "Name resolution intermittent across {site}",
    ),
    _t(
        "firewall",
        Category.NETWORK,
        _NET,
        9,
        0.3,
        "Port blocked between {service} and the partner gateway",
        "traffic to the vendor endpoint is being dropped at the edge",
        "Need the path to {service} reopened, packets time out at the perimeter",
    ),
    _t(
        "link_down",
        Category.NETWORK,
        _NET,
        8,
        0.7,
        "Branch link down at {site}, nobody can reach anything",
        "whole floor lost connectivity at {site}, switch lights are amber",
        "MPLS circuit flapping, high packet loss at {site}",
    ),
    _t(
        "password",
        Category.ACCESS,
        _IAM,
        2,
        0.05,
        "Forgot my password and the self service reset is not sending a code",
        "password expired while on leave, cannot sign in",
        "Locked out after too many attempts, error {code}",
    ),
    _t(
        "mfa",
        Category.ACCESS,
        _IAM,
        3,
        0.1,
        "Authenticator prompts never arrive on my new phone",
        "MFA token lost, need the second factor re-registered",
        "stuck on the verification step after changing handset",
    ),
    _t(
        "role_request",
        Category.ACCESS,
        _IAM,
        12,
        0.05,
        "Need the approver role in {app} for quarter end",
        "my permissions in {app} disappeared after the team move",
        "Please grant read access to the {app} finance module",
    ),
    _t(
        "sso",
        Category.ACCESS,
        _IAM_NET,
        6,
        0.4,
        "Single sign on to {app} fails with {code}",
        "SAML redirect loop when opening {app}",
        "cannot log in to {app}, the identity provider page times out",
    ),
    _t(
        "shared_drive",
        Category.ACCESS,
        _IAM_NET,
        7,
        0.1,
        "Access denied on the shared drive for the finance folder",
        "cannot open the team share from {site}, says no permission",
        "Network folder prompts for credentials again and again",
    ),
    _t(
        "laptop_fail",
        Category.HARDWARE,
        _EUC,
        16,
        0.1,
        "My {device} will not power on after the latest update",
        "laptop shows a black screen and fans run loudly on my {device}",
        "{device} overheats and shuts down in the middle of work",
    ),
    _t(
        "peripherals",
        Category.HARDWARE,
        _EUC,
        8,
        0.03,
        "Docking station does not detect the second monitor",
        "keyboard and mouse stop responding when docked",
        "external display flickers on my {device}",
    ),
    _t(
        "printer",
        Category.HARDWARE,
        _EUC,
        6,
        0.05,
        "Printer on the second floor at {site} shows paper jam constantly",
        "print jobs stay queued on the {site} multifunction device",
        "Cannot print from my {device}, device offline",
    ),
    _t(
        "battery",
        Category.HARDWARE,
        _EUC,
        12,
        0.03,
        "Battery swollen on my {device}, need a replacement",
        "laptop lasts twenty minutes unplugged",
        "charger not recognised by my {device}",
    ),
    _t(
        "install",
        Category.SOFTWARE,
        _APP_EUC,
        8,
        0.05,
        "Need {app} client installed on my {device}",
        "installer fails with {code} on the {app} desktop tool",
        "software center cannot deploy the {app} package",
    ),
    _t(
        "app_crash",
        Category.SOFTWARE,
        _APP,
        10,
        0.3,
        "{app} crashes when exporting the monthly report",
        "{app} freezes on the dashboard and shows {code}",
        "unhandled exception in {app} after clicking submit",
    ),
    _t(
        "app_slow",
        Category.SOFTWARE,
        _APP,
        13,
        0.4,
        "{app} is extremely slow since this morning",
        "pages in {app} take a minute to load for the whole team",
        "users report timeouts in {app} at month end",
    ),
    _t(
        "patch",
        Category.SOFTWARE,
        _APP_EUC,
        9,
        0.1,
        "After update {code} the {app} plugin stopped loading",
        "new release of {app} broke the macros we use",
        "compatibility issue between {app} and the latest Windows patch",
    ),
    _t(
        "data_mismatch",
        Category.SOFTWARE,
        _APP,
        15,
        0.3,
        "Totals in {app} do not match last week's numbers",
        "records duplicated in {app} after the nightly sync",
        "{app} report shows missing rows for some customers",
    ),
    _t(
        "db_conn",
        Category.DATABASE,
        _DBA_APP,
        6,
        0.6,
        "Connection pool exhausted on {db}, {service} throwing {code}",
        "cannot connect to {db}, too many clients",
        "application reports {code} when reaching {db}",
    ),
    _t(
        "db_slow",
        Category.DATABASE,
        _DBA_APP,
        12,
        0.5,
        "Long running queries are blocking {db}",
        "lock contention on {db} is stalling {service}",
        "query plan regressed on {db}, batch job runs for hours",
    ),
    _t(
        "replication",
        Category.DATABASE,
        _DBA,
        11,
        0.5,
        "Replication lag on {db} over thirty minutes",
        "standby for {db} has stopped applying logs",
        "read replica of {db} returns stale data",
    ),
    _t(
        "backup",
        Category.DATABASE,
        _DBA,
        9,
        0.3,
        "Nightly backup of {db} failed again",
        "restore test of {db} did not complete",
        "backup storage full for {db}",
    ),
    _t(
        "disk_full",
        Category.DATABASE,
        _DBA,
        5,
        0.6,
        "Tablespace almost full on {db}",
        "data volume for {db} at ninety eight percent",
        "transaction log growing without limit on {db}",
    ),
    _t(
        "k8s",
        Category.CLOUD,
        _CLOUD_APP,
        9,
        0.6,
        "Pods for {service} are in CrashLoopBackOff",
        "{service} deployment stuck rolling out, containers restart",
        "cluster nodes NotReady, {service} replicas pending",
    ),
    _t(
        "vm",
        Category.CLOUD,
        _CLOUD,
        8,
        0.4,
        "Virtual machine hosting {service} is unreachable",
        "instance for {service} failed status checks",
        "autoscaling group is not replacing unhealthy hosts",
    ),
    _t(
        "storage",
        Category.CLOUD,
        _CLOUD,
        7,
        0.3,
        "Object storage bucket for {service} returning {code}",
        "persistent volume for {service} is full",
        "file gateway latency very high for {service}",
    ),
    _t(
        "lb",
        Category.CLOUD,
        _CLOUD_APP,
        6,
        0.7,
        "Load balancer returning {code} for {service}",
        "health checks failing behind the ingress for {service}",
        "TLS certificate expired on the {service} endpoint",
    ),
    _t(
        "cicd",
        Category.CLOUD,
        _CLOUD_APP,
        10,
        0.15,
        "Build pipeline for {service} fails at the deploy stage",
        "release runner out of capacity, {service} deploy queued",
        "terraform apply failing on the {service} stack",
    ),
    _t(
        "phish",
        Category.SECURITY,
        _SEC,
        4,
        0.3,
        "Suspicious mail asking me to confirm my password",
        "I clicked a link in a fake invoice email, then typed my credentials",
        "several colleagues got the same phishing message",
    ),
    _t(
        "malware",
        Category.SECURITY,
        _SEC,
        12,
        0.7,
        "Endpoint protection flagged a trojan on my {device}",
        "ransom note appeared on a file server at {site}",
        "strange process encrypting files on my {device}",
    ),
    _t(
        "unauth",
        Category.SECURITY,
        _SEC_IAM,
        9,
        0.6,
        "Sign in from another country on my account that was not me",
        "impossible travel alert for a privileged user",
        "unknown admin account created in {app}",
    ),
    _t(
        "data_leak",
        Category.SECURITY,
        _SEC,
        16,
        0.7,
        "Customer file sent to an external address by mistake",
        "API key for {service} found in a public repository",
        "sensitive report shared with an open link",
    ),
    _t(
        "vuln",
        Category.SECURITY,
        _SEC,
        20,
        0.3,
        "Critical CVE reported on {service}, needs assessment",
        "scanner flagged an outdated library in {app}",
        "penetration test finding open on {service}",
    ),
    _t(
        "mailbox",
        Category.EMAIL,
        _APP_EUC,
        5,
        0.05,
        "Mailbox full, cannot send or receive",
        "shared mailbox missing from Outlook",
        "email stuck in outbox after laptop restart",
    ),
    _t(
        "mail_flow",
        Category.EMAIL,
        _APP,
        7,
        0.5,
        "Messages to external customers are bouncing with a relay error",
        "mail delayed by hours for the whole {site}",
        "inbound email from a partner is being rejected",
    ),
    _t(
        "calendar",
        Category.EMAIL,
        _APP_EUC,
        5,
        0.05,
        "Calendar invites do not sync on my phone",
        "cannot see delegate calendars in Outlook",
        "room booking fails with a free busy error",
    ),
    _t(
        "teams",
        Category.EMAIL,
        _APP_EUC,
        4,
        0.15,
        "Teams calls drop audio after a minute",
        "cannot share screen in meetings on my {device}",
        "chat messages not delivered in Teams",
    ),
    _t(
        "sharepoint",
        Category.EMAIL,
        _APP,
        7,
        0.2,
        "SharePoint site for the project returns {code}",
        "document library will not sync to OneDrive",
        "cannot upload files to the team site",
    ),
)

# A reporter describes the symptom, not the cause. Tickets for these topics are sometimes
# worded exactly like the listed topic, so text alone cannot settle the true category.
_SYMPTOM_OVERLAP = {
    "vpn_drop": ("wifi", "sso"),
    "dns": ("mail_flow", "sso", "app_slow"),
    "firewall": ("db_conn", "k8s", "vm"),
    "link_down": ("vm", "wifi"),
    "password": ("sso", "mfa"),
    "sso": ("app_crash", "vpn_drop", "dns"),
    "shared_drive": ("vpn_drop", "storage"),
    "role_request": ("sso", "data_mismatch"),
    "laptop_fail": ("patch", "malware"),
    "peripherals": ("patch", "laptop_fail"),
    "install": ("patch", "app_crash"),
    "app_crash": ("db_conn", "patch"),
    "app_slow": ("db_slow", "wifi", "vm"),
    "patch": ("laptop_fail", "install"),
    "data_mismatch": ("replication", "db_slow"),
    "db_conn": ("app_crash", "k8s", "firewall"),
    "db_slow": ("app_slow",),
    "replication": ("data_mismatch", "link_down"),
    "disk_full": ("storage", "vm"),
    "k8s": ("app_slow", "app_crash"),
    "vm": ("link_down", "app_slow"),
    "storage": ("disk_full", "backup"),
    "lb": ("app_crash", "dns", "sharepoint"),
    "cicd": ("k8s", "install"),
    "phish": ("mailbox", "password"),
    "malware": ("app_slow", "laptop_fail"),
    "unauth": ("password", "mfa"),
    "data_leak": ("sharepoint", "mailbox"),
    "mail_flow": ("dns", "firewall"),
    "mailbox": ("mail_flow",),
    "teams": ("wifi", "vpn_drop"),
    "sharepoint": ("storage", "shared_drive"),
}
SYMPTOM_OVERLAP_RATE = 0.2

_VAGUE = (
    "It is not working since morning, please help",
    "Getting an error when I try to log in and open things",
    "System very slow today, unable to finish my work",
    "same problem as last time, please fix urgently",
    "Nothing loads. Tried restarting. Still broken",
    "Access issue on the application, kindly check",
    "Getting a timeout, was fine yesterday",
    "connection problem again",
)
_VAGUE_CONTEXT = ("at {site}", "on my {device}", "in {app}", "for the team", "since the weekend", "with {service}")
_TOPIC_BY_KEY = {topic.key: topic for topic in TOPICS}
_OPENERS = ("", "", "", "Hi team, ", "Hello, ", "Urgent: ", "Please help. ", "Good morning, ")
_CONTEXT = (
    "",
    "",
    "",
    " It started about an hour ago.",
    " Several people nearby see the same.",
    " Tried rebooting already.",
    " This is blocking a client deliverable.",
    " It was working yesterday.",
    " Happens only sometimes.",
)
_SIGNOFF = ("", "", "", "", " Thanks.", " Regards, Finance Ops.", " Sent from my phone.")
_ACRONYMS = re.compile(r"\b[A-Z]{2,}\b")


def _fill(phrase: str, rng: random.Random) -> str:
    return phrase.format(
        app=rng.choice(APPS),
        site=rng.choice(SITES),
        device=rng.choice(DEVICES),
        service=rng.choice(SERVICES),
        db=rng.choice(DBS),
        code=rng.choice(CODES),
    )


def _typo(text: str, rng: random.Random, rate: float = 0.03) -> str:
    chars = list(text)
    for index in range(len(chars) - 1):
        if chars[index].isalpha() and chars[index + 1].isalpha() and rng.random() < rate:
            chars[index], chars[index + 1] = chars[index + 1], chars[index]
    return "".join(chars)


def _impact_urgency(topic: Topic, rng: random.Random) -> tuple[Level, Level]:
    high = rng.random() < topic.high_impact_rate
    impact = Level.HIGH if high else rng.choices([Level.MEDIUM, Level.LOW], [0.55, 0.45])[0]
    urgency = (
        rng.choices([Level.HIGH, Level.MEDIUM], [0.6, 0.4])[0]
        if high
        else rng.choices([Level.HIGH, Level.MEDIUM, Level.LOW], [0.1, 0.5, 0.4])[0]
    )
    return impact, urgency


def _business_start(moment: datetime) -> datetime:
    """Next time a non-urgent ticket can be picked up: weekdays, 08:00 to 18:00 UTC."""
    while True:
        if moment.weekday() >= 5:
            moment = (moment + timedelta(days=1)).replace(hour=8, minute=0)
        elif moment.hour < 8:
            moment = moment.replace(hour=8, minute=0)
        elif moment.hour >= 18:
            moment = (moment + timedelta(days=1)).replace(hour=8, minute=0)
        else:
            return moment


def _arrivals(rng: np.random.Generator, start: datetime, days: int, daily: float) -> list[datetime]:
    moments = []
    for day in range(days):
        date = start + timedelta(days=day)
        rate = daily * (0.28 if date.weekday() >= 5 else 1.0) * (1 + 0.15 * day / days)
        for _ in range(rng.poisson(rate)):
            hour = np.clip(rng.normal(12.5, 3.8), 0, 23.99)
            moments.append(date + timedelta(hours=float(hour)))
    return sorted(moments)


def generate(days: int = 540, daily_mean: float = 34, seed: int = 42, end: datetime | None = None) -> pd.DataFrame:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    end = end or datetime(2026, 6, 30, tzinfo=UTC)
    start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Temporary staffing shortfalls: conditions the early training period never saw.
    surges = {
        team: (start + timedelta(days=rng.randint(days // 6, days * 5 // 6)), rng.randint(14, 35))
        for team in TEAM_STAFF
    }
    open_by_team: dict[str, list[tuple[datetime, str]]] = {team: [] for team in TEAM_STAFF}
    channels = list(Channel)
    channel_weights = [0.5, 0.25, 0.1, 0.15]
    rows = []

    for index, created in enumerate(_arrivals(np_rng, start, days, daily_mean)):
        topic = rng.choice(TOPICS)
        worded_as = topic
        overlap = _SYMPTOM_OVERLAP.get(topic.key)
        if overlap and rng.random() < SYMPTOM_OVERLAP_RATE:
            worded_as = _TOPIC_BY_KEY[rng.choice(overlap)]
        phrase_index = rng.randrange(len(worded_as.phrases))
        channel = rng.choices(channels, channel_weights)[0]
        title = _fill(worded_as.phrases[phrase_index], rng)
        vague = rng.random() < 0.09
        if channel == Channel.MONITORING:
            title = f"ALERT {_ACRONYMS.sub('', title).strip()}"
            description = title
        elif vague:
            title = f"{rng.choice(_VAGUE)} {_fill(rng.choice(_VAGUE_CONTEXT), rng)}"
            description = title + rng.choice(_CONTEXT)
        else:
            description = (
                rng.choice(_OPENERS)
                + _fill(rng.choice(worded_as.phrases), rng)
                + rng.choice(_CONTEXT)
                + rng.choice(_SIGNOFF)
            )
            if rng.random() < 0.4:
                description = _typo(description, rng)

        category = topic.category
        if rng.random() < 0.06:
            category = rng.choice(list(Category))  # human labelling mistake

        team_names, team_weights = zip(*topic.teams, strict=True)
        team = rng.choices(team_names, team_weights)[0]
        impact, urgency = _impact_urgency(topic, rng)
        priority = compute_priority(impact, urgency)

        queue = open_by_team[team]
        while queue and queue[0][0] <= created:
            heapq.heappop(queue)
        backlog = len(queue)
        backlog_high = sum(1 for _, level in queue if level in ("P1", "P2"))

        staff = TEAM_STAFF[team]
        surge_start, surge_days = surges[team]
        if surge_start <= created < surge_start + timedelta(days=surge_days):
            staff = max(1, staff - 2)
        urgent = priority in ("P1", "P2")
        ahead = backlog_high if urgent else backlog
        wait_hours = max(0, ahead - staff) / staff * (0.5 if urgent else 2.4)
        pickup = created if urgent else _business_start(created)
        pickup += timedelta(hours=wait_hours)

        service_hours = float(np_rng.lognormal(np.log(topic.hours), 0.75))
        service_hours *= {"P1": 0.3, "P2": 0.55, "P3": 1.0, "P4": 1.6}[priority]
        if vague:
            service_hours *= 1.5  # back-and-forth to find out what is wrong
        if not urgent:
            service_hours *= 1.7  # work pauses overnight
        resolved = pickup + timedelta(hours=service_hours)
        heapq.heappush(queue, (resolved, priority))

        target = SLA_TARGET_MINUTES[priority]
        duration = (resolved - created).total_seconds() / 60
        rows.append(
            {
                "ticket_id": index + 1,
                "created_at": created,
                "resolved_at": resolved,
                "title": title,
                "description": description,
                "category": category.value,
                "topic": topic.key,
                "phrase_id": f"{worded_as.key}:{phrase_index}",
                "team": team,
                "channel": channel.value,
                "impact": impact.value,
                "urgency": urgency.value,
                "priority": priority.value,
                "team_backlog": backlog,
                "team_backlog_high": backlog_high,
                "resolution_minutes": round(duration, 1),
                "sla_target_minutes": target,
                "sla_breached": int(duration > target),
            }
        )
    return pd.DataFrame(rows)

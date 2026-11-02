"""Load the synthetic demo: python -m scripts.seed_demo [--incidents N]

Idempotent reference data, then, on an empty database, a recent incident history generated
with a different seed from the training data. DEMO_PASSWORD must be set in the environment.
"""

import argparse
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import Category, Channel, Level, Priority, Role, Status
from app.core.security import hash_password
from app.db.session import new_session
from app.ml.synthetic import TEAM_STAFF, generate
from app.models import Incident, Runbook, SLAPolicy, Team, User
from app.rag import ingest
from app.services import remediation, sla, triage
from app.services.sla import DEFAULT_TARGETS

logger = logging.getLogger("seed")

OPEN_TICKETS = 30

TEAM_DESCRIPTIONS = {
    "Network Operations": "LAN, WAN, VPN, DNS and firewalls",
    "Identity & Access": "Accounts, MFA, SSO and permissions",
    "End User Computing": "Laptops, peripherals, printing and client software",
    "Application Support": "Business applications and collaboration services",
    "Database Administration": "Database availability, performance and backups",
    "Cloud Platform": "Kubernetes, compute, storage and delivery pipelines",
    "Security Operations": "Security monitoring and incident response",
}

RESOLUTIONS = {
    "vpn_drop": "Updated the VPN client and switched the profile from UDP to TCP. The session stayed up for a full working day.",
    "wifi": "Forgot and rejoined the corporate SSID, and Network Operations rebalanced the nearest access point.",
    "dns": "One resolver had stale records. Removed it from rotation, restarted the service and flushed client caches.",
    "firewall": "The deny log confirmed a policy block. An approved change opened the required port between the two services.",
    "link_down": "The carrier repaired the primary circuit. Traffic ran on the backup link until service was restored.",
    "password": "Verified the user's identity, reset the password and cleared old credentials from their devices.",
    "mfa": "Issued a temporary access pass and the user registered the authenticator on the new device.",
    "role_request": "Application owner approved the request. Role added and access confirmed after a new sign in.",
    "sso": "The SAML signing certificate had expired. Rotated it and updated the application configuration.",
    "shared_drive": "User was missing from the folder security group. Added them, and access worked after signing back in.",
    "laptop_fail": "Display cable had failed. Device repaired and a loan laptop was provided in the meantime.",
    "peripherals": "Reset the dock and updated its firmware and the graphics driver, which restored the monitors.",
    "printer": "Cleared the jam and restarted the print service for this location.",
    "battery": "Replaced the battery through the hardware catalogue.",
    "install": "Device had a pending restart. After rebooting, the package deployed from the software centre.",
    "app_crash": "Traced to a defect in the last release. Rolled back and raised a fix with the vendor.",
    "app_slow": "Blocking database queries caused the slowdown. The batch job was rescheduled and latency returned to normal.",
    "patch": "Paused the patch ring and removed the update from affected devices until a fixed version shipped.",
    "data_mismatch": "A retried sync created duplicates. Paused the job, corrected records through the application, and added an idempotency check.",
    "db_conn": "A service was leaking connections. Terminated idle sessions, restarted the service and put a pooler in front of the database.",
    "db_slow": "Stale statistics caused a poor plan. Ran ANALYZE and rescheduled the heavy batch outside peak hours.",
    "replication": "A long query on the standby held back replay. Cancelled it and the replica caught up.",
    "backup": "The repository was full. Adjusted retention, reran the backup and verified it with a restore test.",
    "disk_full": "An inactive replication slot was retaining WAL. Dropped it after confirming it was unused, then extended the volume.",
    "k8s": "Exit code 137 showed the container exceeding its memory limit. Rolled back and raised the limit in the pipeline.",
    "vm": "System status check failed on the host. Stopped and started the instance to move it to healthy hardware.",
    "storage": "Expired service credentials caused the 403 responses. Rotated them and access returned.",
    "lb": "Certificate auto-renewal had failed on its DNS validation. Renewed the certificate and reloaded the ingress.",
    "cicd": "Fixed the first failing step and cleared a stale Terraform lock after confirming no apply was running.",
    "phish": "Purged the message from mailboxes, blocked the sender, and reset the credentials of anyone who entered them.",
    "malware": "Isolated the host, removed the malware, and rebuilt the device after finding no lateral movement.",
    "unauth": "Revoked sessions, reset credentials, and reviewed activity since the first suspicious sign in.",
    "data_leak": "Rotated the exposed secret first, reviewed its use since exposure, and informed the privacy office.",
    "vuln": "Confirmed the component was reachable, patched it within the agreed window and verified with a rescan.",
    "mailbox": "Archived old mail and cleared large attachments, which brought the mailbox under quota.",
    "mail_flow": "The sending IP was on a blocklist after a DNS change broke SPF. Fixed the record, requested delisting and retried the queue.",
    "calendar": "Removed and re-added the work account on the phone, and the calendar synced correctly.",
    "teams": "Cleared the Teams cache and signed back in, which fixed audio and screen sharing.",
    "sharepoint": "The site had reached its storage quota. Increased it and the library synced again.",
}

DEMO_USERS = [
    ("admin@example.com", "Asha Admin", Role.ADMIN, None),
    ("manager@example.com", "Mohan Manager", Role.MANAGER, "Network Operations"),
    ("secmanager@example.com", "Sara Sec-Manager", Role.MANAGER, "Security Operations"),
    ("agent@example.com", "Neil Network", Role.AGENT, "Network Operations"),
    ("iam.agent@example.com", "Ira Identity", Role.AGENT, "Identity & Access"),
    ("euc.agent@example.com", "Evan Endpoint", Role.AGENT, "End User Computing"),
    ("app.agent@example.com", "Aditi Apps", Role.AGENT, "Application Support"),
    ("dba.agent@example.com", "Dev Database", Role.AGENT, "Database Administration"),
    ("cloud.agent@example.com", "Chitra Cloud", Role.AGENT, "Cloud Platform"),
    ("sec.agent@example.com", "Sam Security", Role.AGENT, "Security Operations"),
    ("user@example.com", "Uma User", Role.REQUESTER, None),
    ("user2@example.com", "Rohan Requester", Role.REQUESTER, None),
]


def seed_reference_data(db: Session, password: str) -> None:
    for name in TEAM_STAFF:
        if db.scalar(select(Team).where(Team.name == name)) is None:
            db.add(Team(name=name, description=TEAM_DESCRIPTIONS[name]))
    db.flush()
    for priority, (response, resolution) in DEFAULT_TARGETS.items():
        if db.get(SLAPolicy, priority) is None:
            db.add(SLAPolicy(priority=priority, response_minutes=response, resolution_minutes=resolution))
    for key, name, description, action, category in remediation.DEFAULT_RUNBOOKS:
        if db.scalar(select(Runbook).where(Runbook.key == key)) is None:
            db.add(Runbook(key=key, name=name, description=description, action=action, category=category))
    teams = {team.name: team.id for team in db.scalars(select(Team))}
    password_hash = hash_password(password)
    for email, full_name, role, team in DEMO_USERS:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(
                User(
                    email=email,
                    full_name=full_name,
                    password_hash=password_hash,
                    role=role,
                    team_id=teams.get(team) if team else None,
                )
            )
    db.commit()


def seed_incidents(db: Session, count: int, seed: int = 2026) -> int:
    if db.scalar(select(func.count()).select_from(Incident)):
        logger.info("Incidents already present; skipping history")
        return 0
    rng = random.Random(seed)
    now = datetime.now(UTC)
    days = 90
    history = generate(days=days, daily_mean=count / days / 0.8, seed=seed, end=now)
    history = history[history["created_at"] < now].tail(count)
    open_tickets = set(history["ticket_id"].tail(OPEN_TICKETS))

    teams = {team.name: team.id for team in db.scalars(select(Team))}
    requesters = list(db.scalars(select(User).where(User.role == Role.REQUESTER)))
    agents: dict[int, list[User]] = {}
    for agent in db.scalars(select(User).where(User.role == Role.AGENT)):
        agents.setdefault(agent.team_id, []).append(agent)

    resolved = []
    for row in history.itertuples():
        created = row.created_at.to_pydatetime()
        resolved_at = row.resolved_at.to_pydatetime()
        team_id = teams[row.team]
        # The simulator resolves most tickets within hours, so hold the newest back as a
        # working queue, spread across their SLA windows: some safe, some close, a few late.
        is_open = row.ticket_id in open_tickets
        if is_open:
            created = now - timedelta(minutes=row.sla_target_minutes * rng.uniform(0.05, 1.1))
        priority = Priority(row.priority)
        incident = Incident(
            title=row.title[:200],
            description=row.description,
            impact=Level(row.impact),
            urgency=Level(row.urgency),
            priority=priority,
            channel=Channel(row.channel),
            category=Category(row.category),
            requester_id=rng.choice(requesters).id,
            team_id=team_id,
            created_at=created,
            updated_at=now if is_open else resolved_at,
        )
        sla.apply_due_dates(db, incident, created)
        if is_open:
            incident.status = rng.choice((Status.NEW, Status.ASSIGNED, Status.IN_PROGRESS))
            incident.assignee_id = None if incident.status == Status.NEW else rng.choice(agents[team_id]).id
            if incident.status == Status.IN_PROGRESS:
                incident.first_response_at = created + timedelta(minutes=rng.randint(5, 60))
        else:
            old = resolved_at < now - timedelta(days=7)
            incident.status = Status.CLOSED if old else Status.RESOLVED
            incident.closed_at = resolved_at + timedelta(days=7) if old else None
            incident.resolved_at = resolved_at
            incident.assignee_id = rng.choice(agents[team_id]).id
            incident.first_response_at = created + timedelta(minutes=rng.randint(5, 120))
            incident.resolution_notes = RESOLUTIONS[row.topic]
            incident.sla_breached = bool(row.sla_breached)
            incident.sla_breached_at = incident.resolution_due_at if row.sla_breached else None
        db.add(incident)
        db.flush()
        if is_open:
            triage.classify(db, incident)
            triage.route(db, incident)
        triage.score_sla_risk(db, incident, (row.team_backlog, row.team_backlog_high))
        if not is_open:
            resolved.append(incident)
    db.commit()

    logger.info("Indexing %d resolved incidents", len(resolved))
    for position, incident in enumerate(resolved, start=1):
        ingest.index_resolved_incident(db, incident)
        if position % 100 == 0:
            db.commit()
            logger.info("  %d", position)
    db.commit()
    return len(history)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incidents", type=int, default=800)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    password = get_settings().demo_password
    if not password or len(password) < 12:
        raise SystemExit("Set DEMO_PASSWORD (12 characters or more) before seeding")

    with new_session() as db:
        seed_reference_data(db, password)
        logger.info("Knowledge base: %s", ingest.ingest_directory(db))
        logger.info("Incidents created: %d", seed_incidents(db, args.incidents))
        logger.info("SLA check: %s", sla.run_sla_check(db))


if __name__ == "__main__":
    main()

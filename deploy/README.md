# deploy

What keeps the API running on a VPS, and what stops its logs filling the disk.
Three files, none of which the application knows about — it writes to stdout and
listens on a port, and everything here is the box's side of that.

## Install

```bash
sudo useradd --system --home /opt/interview-lm --shell /usr/sbin/nologin interview-lm
sudo usermod -aG docker interview-lm          # serve.sh runs a container

sudo git clone https://github.com/Priyanshu2425/interview-lm-backend.git /opt/interview-lm
cd /opt/interview-lm
sudo cp .env.prod.example .env.prod && sudo $EDITOR .env.prod
sudo docker build -t interview-lm backend/

# The log directory is not created by anything else. systemd's `append:` fails
# the unit if the directory is missing, which is a clearer failure than a
# service that starts and logs nowhere.
sudo mkdir -p logs
sudo chown -R interview-lm:interview-lm /opt/interview-lm
sudo chmod 600 .env.prod

sudo cp deploy/interview-lm.service /etc/systemd/system/
sudo cp deploy/interview-lm.logrotate /etc/logrotate.d/interview-lm
sudo systemctl daemon-reload
sudo systemctl enable --now interview-lm
```

Then check it is actually up, rather than merely started:

```bash
systemctl status interview-lm
curl -s localhost:8000/v1/health/live      # {"service":"interview-lm","version":"..."}
curl -s localhost:8000/v1/health           # this one reaches Neon
```

## Keeping it running

`interview-lm.service` is the supervisor. `Restart=always` covers a crash and a
reboot both.

The part worth understanding is `StartLimitBurst=5` over `StartLimitIntervalSec=300`.
Without it, a process that cannot boot at all — one missing variable, a bad
`DATABASE_URL` — restarts forever, and the symptom is a machine at full CPU
writing the same traceback until the disk fills. With it, systemd gives up after
five failures in five minutes and leaves the unit in `failed`, which is a state
you can see:

```bash
systemctl reset-failed interview-lm && systemctl start interview-lm
```

`scripts/serve.sh` is the same start, runnable by hand, and is deliberately not
a `while true` loop for the reason above — a shell loop has no backoff.

## Logs

Both streams land in `logs/interview-lm.log`, appended rather than truncated so
a restart does not erase the crash that caused it. journald keeps its own copy;
`journalctl -u interview-lm -f` and `tail -f logs/interview-lm.log` show the
same thing.

`interview-lm.logrotate` rotates daily and keeps seven, so nothing on disk is
older than a week — `rotate 7` is the whole retention policy, and the eighth
day's rotation deletes the oldest. The distribution's own logrotate timer runs
it; there is no cron entry to add.

Two directives that are load-bearing rather than stylistic:

- **`copytruncate`** — required, not preferred. systemd holds the file open via
  `append:`, so renaming it would leave the service writing to an inode with no
  name: the live log would look empty while the disk kept filling. Copying then
  truncating keeps the inode.
- **`notifempty`** — a box nobody has used yet produces a zero-byte log, and
  rotating it daily would burn all seven slots on nothing and evict the week you
  cared about.

Check the plan without waiting a day:

```bash
sudo logrotate -d /etc/logrotate.d/interview-lm    # dry run
sudo logrotate -f /etc/logrotate.d/interview-lm    # force one now
```

## Updating

```bash
cd /opt/interview-lm && sudo git pull
sudo docker build -t interview-lm backend/
sudo systemctl restart interview-lm
```

There are no migrations to run: `create_core` and `create_content` apply their
DDL idempotently on every boot.

## What is not here

**nginx.** The API listens on `127.0.0.1:8000` — bound to loopback in
`serve.sh`, so nothing reaches it from outside without a proxy in front. Serving
the built surface from the same nginx and proxying `/v1` to this port is what
keeps the deployment single-origin, and single-origin is what makes
`ALLOWED_ORIGINS` and `VITE_API_URL` unnecessary (ADR-0020).

**The database.** Neon, deliberately off this box: it holds Evidence, Evidence
outlives any one deployment (ADR-0003), and a database on the machine it serves
dies when you rebuild the machine.

**Uploaded documents.** In R2, not on this box — see `.env.prod.example`. Since
ISSUE-0033 the stored document is the only copy of what a Candidate handed over,
which is exactly why it does not live on a single machine.

The `interview_lm_content` volume `serve.sh` mounts is therefore a cache and not
a store: with R2 configured nothing durable is written to it, and with
`EMBEDDING_PROVIDER=openrouter` there are no model weights to cache either. It
is mounted anyway so that a deployment which later turns R2 off does not
silently start writing the only copy of a document to a container layer. Nothing
on this box needs backing up; back up the bucket.

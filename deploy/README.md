# GoHMotech public web beta

Target requested: https://gohmotech.site. On September 8, 2026 both the apex and
www resolve to 31.43.160.6 and 31.43.161.6 and serve Framer. Do not replace those
records until the origin passes checks. The user has approved replacing the Framer
site. Public NS lookup returns dns1.registrar-servers.com and
dns2.registrar-servers.com (Namecheap BasicDNS). Access to the domain's DNS controls
is still needed; no DNS records have been changed.

The user subsequently reported removing Framer. The private beta environment now
exists at `/home/gohmotech/.config/gohmotech/beta.env` (mode 600), with a new Django
secret and database password. Existing SMTP/OAuth configuration was copied without
sending messages. Database provisioning could not run because sudo requires the
Pi owner's password; the existing database account lacks global administration.

To finish the local installation, run this in the Raspberry Pi terminal:

```bash
sudo bash /home/gohmotech/capstone/deploy/install_beta.sh
```

The installer creates a private source/configuration backup, installs nginx/Redis,
provisions and migrates only the dedicated beta database, checks configuration,
serves collected assets, installs the service, and checks the loopback origin.
Installation completed on September 8, 2026. The recorded private backup is
`/var/backups/gohmotech-beta/20260908T144740Z`. Independent loopback checks passed
for marketplace, login, static assets, anonymous hardware rejection, and private
document rejection. The installer does not configure Cloudflare, alter DNS, or
send email. Enter sudo credentials only in
your local terminal. Then create the beta administrator using the command printed
by the installer. Public exposure still requires the authenticated tunnel and DNS.

Cloudflare activation and apex publication completed September 8, 2026. Public DNS
now returns `apollo.ns.cloudflare.com` and `cora.ns.cloudflare.com`, with Cloudflare
proxy addresses for the apex. The connected tunnel is
`0eeaf8fe-8e53-4e2e-aefa-d91d48c4ee6a`; the apex published application route targets
`http://127.0.0.1:8080`. Keep its token out of chat and source control.

Public checks with a browser user agent passed: HTTP redirects to HTTPS (301), the
apex redirects to marketplace (302), marketplace/login/static CSS return 200,
anonymous hardware reads return 403, and a private nonexistent document returns
404. Application HTTPS responses include HSTS with max-age=3600. An initial request
using the default Python user agent received 403 at the public edge, so remote
machine-client behavior still needs separate validation before connecting devices.
The beta preflight also passed for the actual database, migrations, Redis, and
collected assets. SMTP configuration exists, but real delivery is not verified.
There are currently zero active beta superusers. Create the beta administrator
interactively before operator testing. The www route has not been verified.

The first login/signup attempt exposed Gmail SMTP error 535 (bad credentials).
Replace the Gmail app password in the private beta environment and restart the
service, or temporarily set `BETA_EMAIL_VERIFICATION=none` for a controlled beta
while delivery is repaired. Restore `mandatory` after SMTP works.

Google sign-in needs these exact Authorized redirect URIs in Google Cloud Console:
`https://gohmotech.site/accounts/google/login/callback/` and, after enabling www,
`https://www.gohmotech.site/accounts/google/login/callback/`. While the OAuth
consent screen is in Testing, add each tester under Test users; otherwise publish
the consent screen after completing Google's verification requirements.

## Initial beta behavior

Marketplace workflows remain available. Public signup requires email verification.
Farm screens require an active farm account. IoT and feeding writes return 503;
authenticated BLE receiver ingestion remains available. This deliberately excludes
physical control from the first public web beta. No Celery worker or Beat service
is supplied: the current feeder schedulers need repair and bench testing first.
SMS delivery is disabled. Camera/model actions retain their existing permissions.
WebSockets require an active farm account. Media requests are authorized by Django,
including seller verification documents; nginx must never alias the media directory.

Use a separate beta database and uploads. No production farm data is copied by this
package. Provision a beta administrator and synthetic records before inviting testers.

## Prepare the Raspberry Pi

Prerequisites: MariaDB, Redis, nginx, project dependencies, and an HTTPS ingress.
The included nginx config binds only to loopback for a tunnel origin. It is not a
public HTTP/TLS listener. Configure edge HTTPS redirects before attaching DNS.
Cloudflare Tunnel is one possible ingress if the domain/account supports it; its
credentials and DNS changes must be configured in the domain owner's account.

1. Copy `beta.env.example` to `/home/gohmotech/.config/gohmotech/beta.env`, make it
   readable only by the service user (`chmod 600`), and fill in a new random secret,
   dedicated beta database credentials, and working SMTP settings. Never reuse the
   development Django secret or commit the resulting file.
2. Create `gohmotech_beta` in MariaDB with UTF-8 and a dedicated account restricted
   to that database. Do not grant access to the existing farm database.
3. Create the directories under `BETA_DATA_ROOT`, owned by `gohmotech`.
4. Run from the project directory:

   ```bash
   .venv/bin/python manage.py migrate --settings=config.beta
   .venv/bin/python manage.py collectstatic --noinput --settings=config.beta
   .venv/bin/python manage.py createsuperuser --settings=config.beta
   .venv/bin/python deploy/preflight.py
   ```

5. Copy collected static files from `BETA_DATA_ROOT/static/` into
   `/var/www/gohmotech-beta/static/` with directory mode 755 and file mode 644.
   Copy only collected static assets, never environment files or uploads.
6. Install `gohmotech-beta.service` into `/etc/systemd/system/` and
   `nginx-beta.conf` into nginx's enabled configuration. Validate with `nginx -t`
   and `systemd-analyze verify` before starting. Start Redis, nginx, and the beta
   service. Do not start a beta Celery worker or Beat process.
7. Check the loopback origin with the intended Host header, including marketplace,
   login, static assets, and unauthenticated farm/device rejection. Test actual
   email delivery with an explicitly authorized test recipient.
8. Establish the authenticated HTTPS ingress to `http://127.0.0.1:8080` and enable
   HTTP-to-HTTPS redirects at the edge. Keep 8010, 8080, MySQL, and Redis private.
9. Export the previous DNS records. Change the selected hostnames only after the
   current Framer site's replacement is confirmed. Verify HTTPS, static/media,
   signup, permissions, and WebSockets from outside the local network.

If using a different hostname, update `BETA_ALLOWED_HOSTS`, nginx `server_name`,
the ingress hostname, and any Google OAuth redirect registrations together.

## Release and rollback

Record the exact source snapshot (the existing workspace has uncommitted changes),
dependency versions, environment backup location, database backup, media backup,
and previous DNS values. Backups contain private data and must not be web-served.

For a failed first cutover, restore the saved DNS values to Framer and stop the beta
service; preserve the beta database and uploads for investigation. For subsequent
application rollbacks, check migration compatibility before switching source code.
Do not overwrite new tester activity with an old database backup without a recovery
decision. Rehearse restoration in an isolated database.

See `docs/BETA_TEST_PLAN.md` for tester scenarios. A successful Django deployment
check does not prove SMTP delivery, hardware reliability, or end-to-end operation.

References: [Django deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/),
[Channels channel layers](https://channels.readthedocs.io/en/stable/topics/channel_layers.html),
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).

# First-time onboarding

Farm Owners and approved marketplace sellers receive separate walkthroughs of the existing interface. Administrators, Farm Operators, buyers, and pending/rejected/suspended sellers are excluded. Existing role precedence applies: an owner who can also sell receives the owner tour.

## Setup

For the existing Pi production service, use the scoped installer:

```sh
sudo bash /home/gohmotech/capstone/deploy/install_onboarding.sh
```

It checks production configuration, backs up any existing copies of the tutorial assets, including the mascot PNGs, applies only the dashboard migration, publishes those assets to the collected and nginx static directories, restarts the web service, and runs read-only smoke checks. It needs the Pi administrator password because the nginx static directory is root-owned. The application service loads source directly from this workspace, so its restart uses the current workspace code. Workers, scheduling, and the BLE service are not restarted.

For other deployments:

Run the new migration with the settings used by the target deployment, then collect static assets through the existing deployment process:

```sh
.venv/bin/python manage.py migrate dashboard
.venv/bin/python manage.py collectstatic --noinput
```

This change does not modify authentication, permission rules, or login redirects. Existing eligible accounts with no onboarding record receive the tour on their next eligible page visit, as do newly registered/approved accounts. Account verification and required profile completion happen before onboarding. No production migration or deployment is performed by the test suite.

## State and replay

`dashboard.OnboardingProgress` is a one-to-one record for the existing Django user. `has_completed_tutorial`, `completed_at`, and `completion_reason` permanently record finishing or skipping. Progress for an unfinished automatic tour is also saved in the database, so it resumes after a page change, refresh, or new browser login. Accounts whose role changes retain their completion status; their manual replay uses the current role.

The POST-only mutations at `dashboard:tutorial_state` use the logged-in account, normal Django CSRF protection, validated actions/step bounds, and database locking. GET and POST responses are marked no-store. Completion cannot be reset by a stale step update. No account ID or role supplied by the browser is trusted.

Owners can select **Help & Settings → Help · Take Tour Again**. Sellers can select **My account → Help · Take Tour Again** (inside the navigation menu on mobile). Replay progress is stored separately in the Django session, leaving permanent completion untouched. Skipping or finishing a replay closes it; if the original tour had never been dismissed, this also records completion.

The shared widget fetches fresh state when a page loads, when a cached page is restored, and when the tab becomes visible. A failed completion save leaves the walkthrough open with a retry message. Initial state failures leave the existing page usable. The tutorial makes no farm, equipment, listing, reservation, message, or notification mutations.

## Tour maintenance and checks

Steps and URL reversals live in `dashboard/onboarding.py`; spotlight selectors refer to existing elements, with heading fallbacks for changed layouts. The shared script and stylesheet are `static/js/onboarding.js` and `static/css/onboarding.css`. Both existing base templates include the same widget; no third-party walkthrough package is required.

```sh
.venv/bin/python deploy/test_isolated.py dashboard.test_onboarding dashboard.tests iot.test_rbac
```

Automated tests cover role eligibility, persistent completion/skipping, new browser sessions, page progress, replay, stale tabs, role changes, malformed input, CSRF, and successful rendering of every actual tour page. Browser layout checks should cover desktop, tablet, portrait/landscape phones, keyboard navigation, skip confirmation, save failures, and Next/Back page transitions.

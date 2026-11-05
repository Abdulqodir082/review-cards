# Set up free Instagram auto-posting (one time)

This uses Meta's own free Instagram API (no paid tools). You do it once. After
that, Claude adds posts and you approve each one by merging a pull request.

Meta changed the setup in 2026: new apps use **"API setup with Unified login"**,
which needs a **business portfolio**. The good part: the token we make here
(a *system user* token) **never expires**.

Do these on a computer.

---

## Step 1. Instagram must be a professional account linked to a Facebook Page

- Instagram app: **Profile → ☰ → Account type and tools**. If it offers "Switch
  to professional account", do it and pick **Business**.
- Instagram app: **Profile → Edit profile → Page** (or Accounts Center).
  Connect the Otvizcards **Facebook Page**. If you run Meta ads for Otvizcards,
  this is usually done already.

## Step 2. Meta developer app (done ✅)

App **Otvizcards Poster** (type Business) exists at
<https://developers.facebook.com/apps/>.

## Step 3. Connect the app to a business portfolio

In the app: **Instagram → API setup with Unified login → + Business portfolio**.
Pick your existing portfolio (the one your ads use) or create one named
`Otvizcards`. No business verification is needed to post on your own account.

## Step 4. Put Instagram and the Page in the portfolio

Open <https://business.facebook.com/settings> and pick the Otvizcards portfolio.

1. **Accounts → Instagram accounts**: if otvizcards is not listed, **Add** →
   connect it (log in to Instagram yourself).
2. **Accounts → Pages**: make sure the Otvizcards Facebook Page is listed
   (**Add** → it if not).
3. **Accounts → Apps**: make sure **Otvizcards Poster** is listed
   (**Add → Connect an app ID** with the App ID from the developer dashboard).

## Step 5. Create a system user and its token

Still in <https://business.facebook.com/settings>:

1. **Users → System users → Add**. Name `otvizcards-poster`, role **Admin**. Create.
2. Click it → **Assign assets**:
   - **Apps → Otvizcards Poster →** Full control (Manage app).
   - **Instagram accounts → otvizcards →** Full control.
   - **Pages → Otvizcards →** Full control.
   Save.
3. Click **Generate new token**:
   - App: **Otvizcards Poster**
   - Token expiration: **Never**
   - Permissions: tick `instagram_basic`, `instagram_content_publish`,
     `pages_show_list`, `pages_read_engagement`, `business_management`
   - **Generate token**, then **copy** it (it starts with `EAA`).

Do **not** send this token to Claude or anyone in chat. It is a password for your Instagram.
You can leave the app in **Development** mode; Meta does not need to review it.

## Step 6. Put the token in GitHub (safe place)

1. Open <https://github.com/abdulqodir082/review-cards/settings/secrets/actions/new>
2. Name: `IG_ACCESS_TOKEN`
3. Secret: paste the token. Click **Add secret**.

## Step 7. Test it

1. Open <https://github.com/abdulqodir082/review-cards/actions/workflows/instagram.yml>
2. **Run workflow**, keep `check`, click the green **Run workflow**.
3. After ~30 seconds open the run. "Connected to Instagram @otvizcards" means it works.

Then tell Claude "Instagram is set up".

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `IG_ACCESS_TOKEN is not set` | Step 6 again; the name must be exactly `IG_ACCESS_TOKEN`. |
| `Could not pick the Instagram account automatically` | Instagram isn't linked to the Page, or the Page isn't assigned to the system user (Steps 1 and 5.2). Or add a secret `IG_USER_ID` with the Instagram account's ID from Business settings → Instagram accounts. |
| `permission` / `(#10)` / `(#200)` error | Step 5.3: make a new token with all the listed permissions ticked. |
| `Invalid OAuth access token` | Token was deleted or copied wrong. Repeat Step 5.3 and Step 6. |
| `file never became public` | GitHub Pages must be on (repo Settings → Pages → main / root). |

### Older Instagram-Login tokens (start with `IG`)

The poster also accepts these. They last 60 days; the workflow renews them on
the 1st and 15th, and saves the new one if a `GH_SECRETS_PAT` secret
(fine-grained GitHub token with **Secrets: read and write** on this repo) exists.
System-user tokens (`EAA...`) don't need this.

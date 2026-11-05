# Set up free Instagram auto-posting (one time, about 15 minutes)

This uses Meta's own free Instagram API. No paid tools, no Facebook Page needed.
You only do this once. After that, Claude adds posts and you approve them by
merging a pull request.

You need: the otvizcards Instagram login, your Facebook login, and a computer
(the Meta developer site is hard to use on a phone).

---

## Step 1. Make sure otvizcards is a professional account

In the Instagram app: **Profile → ☰ menu → Account type and tools**.
If it says "Switch to professional account", tap it and pick **Business**.
If it already says "Switch to personal account", you are done with this step.

## Step 2. Become a Meta developer (free, one time)

1. Open <https://developers.facebook.com> and log in with your Facebook account.
2. If you have never used it before, you will not see any apps yet. Click
   **Get started** (top right) and finish the short sign-up: accept the terms,
   confirm your phone or email, and pick a role (e.g. "Developer").

## Step 3. Create the app

1. Open <https://developers.facebook.com/apps/creation/>
   (or **My Apps** → **Create App** at the top right).
2. App details: name `Otvizcards Poster`, your email. Click **Next**.
3. Use case: choose **Other**. Click **Next**.
4. App type: choose **Business**. Click **Next**.
5. If it asks about a business portfolio, pick **I don't want to connect a business portfolio yet**.
6. Click through **Next** and **Create app** / **Go to dashboard**.

## Step 4. Add Instagram and copy the token

1. On the app dashboard, scroll to **Instagram** ("Allow creators and businesses
   to ... publish content ...") and click **Set up**.
2. In the left menu open **Instagram → API setup with Instagram login**.
3. Under **1. Generate access tokens**, click **Add account** and log in to
   **otvizcards** on Instagram. Allow everything it asks.
   The Instagram account must be **public** and **professional** (Step 1).
4. Next to otvizcards, click **Generate token**, tick the box, and **copy** the long token.

Skip the other sections on that page (webhooks, business login settings, App Review).
They are only for apps other people use.

Do **not** send this token to Claude or anyone in chat. It is a password for your Instagram.

You can leave the app in **Development** mode. That is fine for posting to your own account, and Meta does not need to review it.

## Step 5. Put the token in GitHub (safe place)

1. Open <https://github.com/abdulqodir082/review-cards/settings/secrets/actions/new>
2. Name: `IG_ACCESS_TOKEN`
3. Secret: paste the token. Click **Add secret**.

## Step 6. Test it

1. Open <https://github.com/abdulqodir082/review-cards/actions/workflows/instagram.yml>
2. Click **Run workflow**, keep `check`, click the green **Run workflow**.
3. After ~30 seconds open the run. A green tick and "Connected to Instagram @otvizcards" means it works.

That's it. Tell Claude "Instagram is set up".

---

## Optional: never think about the token again

Meta tokens last 60 days. The poster renews it automatically on the 1st and
15th of each month, but to save the renewed token GitHub needs one more key:

1. Open <https://github.com/settings/personal-access-tokens/new>
2. Name `instagram token saver`, expiration **No expiration** (or 1 year).
3. Repository access: **Only select repositories → review-cards**.
4. Permissions → Repository permissions → **Secrets: Read and write**. Generate and copy it.
5. Add it as a new secret at the same page as Step 5, named `GH_SECRETS_PAT`.

If you skip this, just repeat Step 4 and Step 5 every ~55 days.

## If something goes wrong

| What you see | What to do |
|---|---|
| `IG_ACCESS_TOKEN is not set` | Do the GitHub secret step again, name must be exactly `IG_ACCESS_TOKEN`. |
| `Invalid OAuth access token` / `Session has expired` | Token expired. Repeat Step 4 and Step 5. |
| `permission` / `(#10)` error | In the app: **App Review → Permissions and features**, make sure `instagram_business_content_publish` is there, then make a new token. |
| `file never became public` | GitHub Pages must be on (repo Settings → Pages → main / root). |

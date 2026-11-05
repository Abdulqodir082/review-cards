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

## Step 2. Create a free Meta developer app

1. Open <https://developers.facebook.com/apps> and log in with Facebook.
   If it asks you to register as a developer, accept and verify your phone.
2. Click **Create app**.
3. App name: `Otvizcards Poster`. Contact email: yours. Click **Next**.
4. Use case: pick **Manage messaging & content on Instagram**. Click **Next**.
5. Business portfolio: choose **I don't want to connect a business portfolio yet**. Click **Next**, then **Create app**.

## Step 3. Turn on posting permission

1. In the app's left menu open **Use cases**, then **Customize** next to the Instagram use case.
2. Under **Permissions**, make sure these are added (click **Add** if not):
   - `instagram_business_basic`
   - `instagram_business_content_publish`

## Step 4. Connect otvizcards and copy the token

1. In the same Instagram use case, open **API setup with Instagram login**.
2. Under **Generate access tokens**, click **Add account** and log in to **otvizcards** on Instagram. Allow everything it asks.
   - If it says the account needs a tester role: go to **App roles → Roles → Add people → Instagram Tester**, type `otvizcards`. Then in Instagram open **Settings → Website permissions → Apps and websites → Tester invites** and accept. Come back and click **Add account** again.
3. Next to otvizcards, click **Generate token**, tick the box, and **copy** the long token.

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
| `IG_ACCESS_TOKEN is not set` | Do Step 5 again, name must be exactly `IG_ACCESS_TOKEN`. |
| `Invalid OAuth access token` / `Session has expired` | Token expired. Repeat Step 4 and Step 5. |
| `permission` / `(#10)` error | Step 3: add `instagram_business_content_publish`, then make a new token. |
| `file never became public` | GitHub Pages must be on (repo Settings → Pages → main / root). |

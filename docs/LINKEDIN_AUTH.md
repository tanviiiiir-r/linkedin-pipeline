# LinkedIn Auth Setup (Free Direct OAuth v2)

Hermes uses the **free** LinkedIn API products for individuals:

- **Share on LinkedIn** — post content as the authenticated member.
- **Sign In with LinkedIn using OpenID Connect** — authenticate and get the member id.

There is no per-post cost. You only pay for your own VPS/compute.

## 1. Create a LinkedIn app

1. Go to [LinkedIn Developer Portal](https://developer.linkedin.com/).
2. Click **Create app**.
3. Fill in the app details and link it to a LinkedIn company page (can be a placeholder page).
4. In the **Auth** tab, add an allowed redirect URL:
   - For local testing: `http://localhost:8000/callback`
   - For a VPS: `https://your-vps-domain/callback` (must be HTTPS for production)
5. In the **Products** tab, request:
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
6. Copy the **Client ID** and **Client Secret** from the **Auth** tab.

## 2. Configure the pipeline

```bash
cd /path/to/linkedin-pipeline
cp .env.example .env
```

Edit `.env`:

```env
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_REDIRECT_URI=http://localhost:8000/callback
TOKEN_SECRET=a_strong_random_secret_at_least_32_chars
```

Generate a token secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Authorize

### Option A: print the URL and paste the code manually

```bash
python run.py linkedin-auth-url
```

Open the printed URL in your browser, authorize the app, then copy the `code` parameter from the redirect URL.

```bash
python run.py linkedin-exchange --code PASTE_CODE_HERE
```

### Option B: local callback server (optional)

If you want a smoother local flow, you can run a small HTTP server on the redirect URI port. This is not built into Hermes yet; paste-the-code is the current supported flow.

## 4. Verify tokens

```bash
python run.py linkedin-status
```

You should see:

```text
Access token present: True
Refresh token present: True
Author URN: urn:li:person:XXXXXXXX
```

## 5. Test a dry-run publish

1. Collect and score items:
   ```bash
   python run.py collect --limit 5
   python run.py score --limit 50
   python run.py draft --limit 1
   ```
2. Approve a draft:
   ```bash
   python run.py queue
   python run.py approve ITEM_ID
   ```
3. Publish (dry-run if no tokens are stored, real if tokens are stored):
   ```bash
   python run.py publish --limit 1
   ```

## Scopes

The default scopes are:

```
openid profile email w_member_social
```

These are the current free scopes. Do **not** use the old deprecated scopes (`r_basicprofile`, `r_liteprofile`).

## Token storage and refresh

Tokens are encrypted with Fernet using your `TOKEN_SECRET` and stored in the same SQLite database as the content pipeline (`content.db`). Access tokens are short-lived, but LinkedIn usually returns a refresh token. Hermes will automatically refresh the access token at publish time if a refresh token is available.

If you ever need to clear tokens:

```bash
python run.py linkedin-logout
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `TOKEN_SECRET is not set` | Add a strong `TOKEN_SECRET` to `.env`. |
| `LinkedIn OAuth credentials are incomplete` | Fill `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI`. |
| `Could not fetch author URN` | Make sure the app has **Sign In with LinkedIn using OpenID Connect** enabled and the `openid` scope is requested. |
| Token exchange fails | Verify the redirect URI in `.env` exactly matches the one in the LinkedIn app settings (including trailing slash). |
| `403` on publish | The app may not have **Share on LinkedIn** approved yet, or the member is not a test user for an unapproved app. |

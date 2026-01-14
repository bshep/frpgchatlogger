To securely set the `DISCORD_CLIENT_SECRET` environment variable, follow these instructions based on your deployment environment:

### 1. For Local Development (using a `.env` file)

This is the recommended approach for development environments as it keeps your secrets out of your codebase.

*   **Create a `.env` file:** In your `backend/` directory, create a new file named `.env`.
*   **Add your secret:** Open `.env` and add the following line, replacing `your_actual_discord_client_secret` with the secret key you obtained from the Discord Developer Portal for your application:
    ```
    DISCORD_CLIENT_SECRET="your_actual_discord_client_secret"
    ```
*   **Restart your backend:** The `backend/main.py` script now includes `load_dotenv()` which will automatically load this secret when the application starts.
*   **Ensure `.env` is in `.gitignore`:** Make sure your `backend/.env` file is listed in your `.gitignore` to prevent it from being committed to version control.

### 2. For EC2 Deployment (via `systemd` service)

If you are deploying your FastAPI backend using a `systemd` service on an EC2 instance, you can configure the environment variable directly within the service unit file.

*   **SSH into your EC2 instance.**
*   **Edit the `systemd` service file:**
    ```bash
    sudo nano /etc/systemd/system/frpgchatlogger_backend.service
    ```
*   **Add the `Environment` directive:** Under the `[Service]` section, add a line for your secret.
    ```
    [Service]
    # ... other directives ...
    Environment="DISCORD_CLIENT_SECRET=your_actual_discord_client_secret"
    # ...
    ```
    Replace `your_actual_discord_client_secret` with your actual secret.
*   **Reload `systemd` and restart the service:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl restart frpgchatlogger_backend.service
    ```

### 3. For GitHub Actions (via GitHub Secrets)

For your GitHub Actions workflow to securely access this secret during deployment (e.g., if any future deployment steps on the runner or remote server require it explicitly, or if the backend itself were built in CI/CD), you should store it in GitHub Secrets.

*   **Go to your GitHub repository settings.**
*   Navigate to **`Secrets and variables`** > **`Actions`**.
*   Click **`New repository secret`**.
*   For **Name**, enter `DISCORD_CLIENT_SECRET`.
*   For **Secret**, paste your `your_actual_discord_client_secret`.
*   Click **`Add secret`**.

This secret will then be available in your GitHub Actions workflows using `${{ secrets.DISCORD_CLIENT_SECRET }}`.

### Important Note on DISCORD_CLIENT_ID:
The `DISCORD_CLIENT_ID` is currently hardcoded in `frontend/beta.html`. If you ever change your Discord application's client ID, you will need to update that file as well. Ideally, sensitive or configurable parameters like `client_id` for the frontend should also be managed via environment variables or a configuration endpoint.
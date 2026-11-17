# Railway deployment settings

`deployment-settings.json` is the reviewed, secret-free settings manifest for use with the Railway plugin. It is documentation/input for the deployment operator, not a file Railway automatically reads. The Dockerfile and start.sh define the runtime. Legacy railway.toml is deliberately omitted because Railway deprecated Config as Code.

Before source cutover, grant Railway's GitHub App access to judy202168/try11111. For each service: apply rootDirectory, dockerfilePath, startCommand and the service's deploy settings with update-service; apply the nonsecret variables listed here with set-variables; then connect-service-source to the repository's main branch. Preserve existing secret variables and worker references. Verify both deployments before removing the obsolete APP_BUNDLE_B64 variables. Do not apply the source runtime settings to the existing Python-image deployment without immediately connecting its GitHub source.

The worker runs hourly but exits outside 8 AM America/Los_Angeles. Preserve its hourly cron and NEVER restart policy. Only the web service has an HTTP health check.

For fully managed Infrastructure as Code later, import the live environment using `railway config pull`, inspect the generated `.railway/railway.ts` with secrets represented by preserve(), and review `railway config plan` before applying. See https://docs.railway.com/infrastructure-as-code.

Current cutover status: source files are uploaded; Railway rejected the repository with “User does not have access to the repo.” Existing image deployments remain active until GitHub integration access is granted.

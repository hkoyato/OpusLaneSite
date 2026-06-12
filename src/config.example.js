// Demo-only configuration for the public static dashboard.
// Copy this file to config.js for local or S3 demo hosting and fill in the values.
// Security note: a credential embedded in a public static site is visible to every visitor
// through browser developer tools and network traffic. This is not production-safe.
window.OPUS_DEMO_CONFIG = {
  apiBaseUrl: "https://example.execute-api.us-west-2.amazonaws.com/prod",
  clientCredential: "replace-with-demo-client-credential"
};

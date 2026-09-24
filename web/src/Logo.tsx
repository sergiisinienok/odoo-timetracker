/** The Particles Global wordmark, self-hosted at /logo.svg (plum #2F0725 on
 * paper). Same-origin on purpose: the CSP allows images from 'self' only. */
export function Logo() {
  return <img className="brand-logo" src="/logo.svg" alt="Particles Global" width={82} height={28} />;
}

import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="auth-shell">
      <section className="auth-copy">
        <span className="product-mark" aria-hidden="true">
          SM
        </span>
        <p className="eyebrow">SMCP operator console</p>
        <h1>Evidence before claims.</h1>
        <p>
          Sign in to inspect compression jobs, measured candidates, artifacts,
          and capsule integrity.
        </p>
      </section>
      <SignIn />
    </main>
  );
}

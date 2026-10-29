import React from "react";

type Props = { active: boolean; children: React.ReactNode };

/** Let a departing scene pause its native work once, then leave its tree alone
 * while other tabs change. Keeping the same native tree preserves scroll,
 * drafts, WebViews and the globe's GL context without Suspense detachment. */
export const RetainedScene = React.memo(
  function RetainedScene({ children }: Props) { return <>{children}</>; },
  (previous: Props, next: Props) => !previous.active && !next.active,
);

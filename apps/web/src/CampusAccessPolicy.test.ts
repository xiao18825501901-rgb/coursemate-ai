import { describe, expect, it } from "vitest";

import { campusVerificationRequired } from "./ui/App.jsx";


describe("campus access policy presentation", () => {
  const campus = { display_type: "campus", requires_student_verification: true };

  it("does not block an unverified registered user while the campus gate is disabled", () => {
    expect(
      campusVerificationRequired(
        { student_verification_required_for_campus: false },
        campus,
        { verified: false },
      ),
    ).toBe(false);
  });

  it("can represent the dormant future gate without affecting private courses", () => {
    const future = { student_verification_required_for_campus: true };
    expect(campusVerificationRequired(future, campus, { verified: false })).toBe(true);
    expect(
      campusVerificationRequired(
        future,
        { display_type: "private", requires_student_verification: false },
        { verified: false },
      ),
    ).toBe(false);
    expect(campusVerificationRequired(future, campus, { verified: true })).toBe(false);
  });
});

# P0 Do-One Authenticated Live Report

Status: PENDING PRODUCTION DEPLOYMENT AND NORMAL CLERK ACCEPTANCE

Local Chrome validation used an explicitly isolated synthetic identity and deterministic provider. It proves browser behavior but is not represented as production authentication.

After deployment this report must record, without cookies or tokens:

- normal Clerk identity confirmation;
- one campus READY course and one owner-private course;
- run/session id and question revision id;
- first display without manual refresh;
- answer submit, explicit reveal, correct answer and independent detail;
- Pair/history, refresh and re-entry recovery;
- provider call count and READY-reuse zero-call evidence;
- second authorized account denial for the private course;
- screenshot/DOM evidence locations.

No fake JWT or `AUTH_TEST_USER_ID` is permitted for the production section.


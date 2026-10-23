# Aperture workbench review · 2026-10-24

## Scope and method

The historical source was inspected before this redesign. See [the dated integration map](historical-integration.md) for the April Gateway/Sentinel/pricing flow, September provider telemetry and rewrite, and October agent/receipt console. The integration changes in this review ship with the repository source.

The selected ImageGen direction is the native 1536 × 1024 concept used during implementation.. It is a design direction selected during implementation, not a claim of user design approval. UI text, controls and layout are React/CSS; the concept is not shipped as an interface image.

The user's in-app browser was used first and again after the final changes to open and close Sentinel without replacing the source. The dedicated Browser plugin was unavailable. The current in-app viewport could not provide the native concept dimensions or the full responsive matrix, so supplemental Playwright used installed Microsoft Edge 156.0.4314.42. Temporary Playwright installation had already been authorized by the user; no browser download or project dependency change was needed.

The concept and latest native-size browser screenshot were both opened with `view_image` in the final visual pass. Screenshots use disabled animations so entrance transitions cannot produce blank captures.

## Fidelity ledger

| Comparison | Concept and rendered evidence | Repair or intentional difference |
| --- | --- | --- |
| Navigation and layout | Full-height 240px navigation, 64px top bar, open page heading and underline mode tabs. | Replaced the floating rounded shell; grouped Workspace, Resources and Network. Python, inference and workflows share one mode bar. |
| Main workbench | A wide source editor beside one continuous Task review inspector; output and input files below the source. | Moved the separate Sentinel workspace into that inspector, moved samples into the editor toolbar and input files under output. Reduced the inspector's previous excessive height. |
| Typography and controls | Roboto for chrome, explicit heading/control sizes and Consolas for source; small corner radii and fine dividers. | Audited labels, fields, tabs, navigation and editor separately. Mobile form text remains 16px where needed for usability. Existing source-byte and keyboard-shortcut information is retained. |
| Palette and surfaces | Neutral gray page, white paper surfaces, dark text and restrained violet action color. | Removed inherited gradients and glow, including the dark-mode wallet button. Dark mode has corresponding neutral surfaces and legible syntax colors. |
| Brand and icons | Aperture branding and consistent outline action icons. | Kept the project's existing logo and SVG icon system instead of recreating the generated logo or replacing functional icons. The task's actual checkbox remains the input-files disclosure control. |
| Copy and state | Compute Studio, its purpose sentence, three workload labels and the five source-to-receipt stages retain the concept's hierarchy. | The primary button reflects real wallet/quote state. An unconnected wallet says Connect wallet; no green safety approval is shown before review. Reviewed-source restrictions, exact runtime/byte information and gateway connectivity remain visible. Payment channel becomes Signed execution in OFF_CHAIN mode. These are deliberate state-dependent changes from the static concept. |
| Responsive behavior | Native concept checked at 1536 × 1024; additional 1440 × 1000, 714 × 764, 390 × 844 and 360 × 800 views. | Sidebar collapses to an icon rail and then bottom navigation. Editor and inspector stack. Sentinel's stage is actionable above the editor; opening it brings the inspector into view on narrow screens. No document-level horizontal overflow was detected. |
| Other workspace surfaces | The same navigation, headings, colors, controls and surfaces continue through all eight routes. | Reworked Provider and Network introductions, placed setup/settlement detail in disclosures, and replaced the long desktop Workflows settings column with paired fields. |

Above-the-fold copy was compared against the concept. Its main headings, source name, modes and stage names are retained. Differences are the real wallet/connection state, exact source metadata, reviewed-source restriction, payment mode and existing branding/icons listed above. The rendered implementation was checked for faithful realization of the selected workbench composition with those intentional functional differences. No material blocking layout mismatch remained in the reviewed states; this is not a claim that all future runtime states or external integrations were verified.

## Integration and verification

A completed Gemini review now carries the owner, gateway identity and receipt hash back to Studio. When the exact source and identity still match, its task ID, source hash and receipt hash become `parameters.aperture_review` in the compute manifest. The gateway checks that the retained Gemini task completed for the same owner with the exact review prompt/source before issuing the quote. The owner signs the manifest digest. Compute output receipts bind that digest, and Studio can download the task manifest. A source edit also clears stale pricing analysis and quote state.

The source review is advisory provenance. It does not replace gateway source policy, execution approval or the user's spending signature.

Validation completed during this task:

- Backend: 112 tests run, OK, with 2 Docker-dependent skips. This includes five source-review regression tests with malformed, stale, foreign-owner and substituted-reference cases.
- Frontend: 61 tests passed. SDK: 41 tests passed. Final frontend lint and production build passed.
- Native Gemini protocol: 14 inference tests passed. A controlled Gemini SSE HTTP fixture was followed by real trusted-local Python execution with the linked review manifest. This is not a live Google response.
- Full browser run: real owner-signed Python execution and matching worker/gateway receipt signatures; editing source invalidated its quote and analysis. A CSV workflow completed three verified steps and produced a report with 8 accepted and 2 skipped rows. Four actual compute tasks were admitted.
- Final visual regression: all eight routes, inline Sentinel open/close, source retention, inference empty state and dark mode checked at all five viewports. No page errors, warning/error console messages or document horizontal overflow were recorded.

Rendered desktop and mobile screenshots plus browser results were retained locally as review evidence and are not part of the source distribution.


The running preview remains OFF_CHAIN, with trusted-host CPU execution and reviewed source samples. Live Gemini requires a configured offer, key and matching worker. APS pressure is still fixed at zero. The 0.5.0 contract source sends a confirmed charge to its assigned worker, but this task did not deploy it or prove a Devnet payout. No GPU execution, permissionless marketplace or Docker isolation is established by these tests.

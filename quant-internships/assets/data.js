/* ─────────────────────────────────────────────────────────────
   data.js — Summer 2027 quant internships. Checked 30 July 2026.

   HOW TO UPDATE
   Every row is one posting. Fields:
     id             stable slug, used for the local "applied" flag — never reuse
     firm           display name
     firm_note      one short clause of context, optional
     title          the posting's own title, verbatim where possible
     role_type      "QT" | "QR" | "QD"   (no SWE/FPGA/HW on this page)
     tier           1 | 2 | 3            rough selectivity/exit read, not a quality ranking
     status         "open" | "soon"      "soon" rows render a date instead of an Apply button
     opens          text for the button when status is "soon"
     locations      array of strings; anything matching /new york|nyc/i sorts first
     apply_url      direct link, firm-hosted where one exists; "" if none found
     eligibility_note  graduation-window language, quoted where available
     comp           display string; "" means not disclosed and renders as such
     comp_source    "posted" if it came from the job description, otherwise who reported it
     comp_rank      approx monthly USD, for sorting only; null if unknown
     multi_apply    short policy string; anything matching /one|single/i renders red
     notes          anything decision-relevant

   RULES
   - Never invent a URL or a compensation figure. Empty string beats a guess.
   - PhD- and Master's-only postings do not belong here. Excluded on this basis:
     Citadel Securities QR (PhD), Citadel QR (PhD), Optiver QR (PhD), SIG QR (Master's
     and PhD), IMC QR (PhD), Five Rings QR (PhD), HRT QR (PhD), Virtu QR (PhD),
     Tower QR (PhD), Jump QR (PhD), Two Sigma AI Research Scientist, D. E. Shaw QA (PhD),
     Voloridge QR Fellowship, Point72/Cubist QR, Quantic PhD QR, Marshall Wace QR.
   - Non-US-based roles excluded: DV Trading (Hong Kong), D. E. Shaw (London),
     Maven Securities (London-led Emerging Talent).
   - Row order inside each tier is the curation order the default sort respects.
   ───────────────────────────────────────────────────────────── */

var ROLES = [

  /* ════ QUANTITATIVE TRADING ══════════════════════════════════ */

  /* — tier 1 — */
  {
    id: "js-qt", firm: "Jane Street", role_type: "QT", tier: 1, status: "open",
    firm_note: "Rolling review. Apply when you can interview within a few weeks.",
    title: "Quantitative Trader Internship (May–August)",
    locations: ["New York"],
    apply_url: "https://www.janestreet.com/join-jane-street/position/8617344002/",
    eligibility_note: "No graduation window stated. Only requirement is strong quantitative thinking.",
    comp: "$300,000 annualized base", comp_source: "posted", comp_rank: 25000,
    multi_apply: "Multiple allowed",
    notes: "Collaborative probability and market-making interviews. Poker and forecasting map directly."
  },
  {
    id: "des-qt", firm: "D. E. Shaw", role_type: "QT", tier: 1, status: "open",
    title: "Proprietary Trading Intern",
    locations: ["New York"],
    apply_url: "https://www.deshaw.com/careers/proprietary-trading-intern-new-york-summer-2027-5731",
    eligibility_note: "Usually approaching the final year of full-time study. Any field.",
    comp: "$25,000/mo + $10,000 sign-on + housing", comp_source: "posted", comp_rank: 25000,
    multi_apply: "Bundle several roles in one application",
    notes: "No finance background required. The application bundle lets you add the Quant Analyst role too."
  },
  {
    id: "cits-qt", firm: "Citadel Securities", role_type: "QT", tier: 1, status: "open",
    title: "Quantitative Trader Intern",
    locations: ["New York", "Miami"],
    apply_url: "https://www.citadelsecurities.com/careers/details/quantitative-trader-intern-us/",
    eligibility_note: "Evergreen role page; no graduation window stated.",
    comp: "$4,500–$5,800/wk + sign-on + housing", comp_source: "posted", comp_rank: 22300,
    multi_apply: "Not stated",
    notes: "Maps unusually well to state-space modeling, backtesting and C++/Python."
  },
  {
    id: "cit-qt", firm: "Citadel", role_type: "QT", tier: 1, status: "open",
    firm_note: "The hedge fund. A separate application from Citadel Securities.",
    title: "Quantitative Trader (Equity Quantitative Research) Intern",
    locations: ["New York", "Greenwich, CT", "Miami"],
    apply_url: "https://www.citadel.com/careers/details/quantitative-trader-equity-quantitative-research-intern-us/",
    eligibility_note: "No graduation window located. Bachelor's or above in a quantitative field.",
    comp: "$4,500–$5,800/wk + sign-on + housing", comp_source: "reported", comp_rank: 22300,
    multi_apply: "Separate firm from Citadel Securities",
    notes: "You may apply to both Citadel and Citadel Securities; they recruit independently."
  },
  {
    id: "fr-qt", firm: "Five Rings", role_type: "QT", tier: 1, status: "open",
    title: "Summer Intern 2027, Quantitative Trader",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/fiveringsllc/jobs/5139668008",
    eligibility_note: "Winter 2027 / spring-summer 2028 graduation.",
    comp: "$300,000 annualized + sign-on + housing", comp_source: "posted", comp_rank: 25000,
    multi_apply: "Allowed but discouraged",
    notes: "Highest posted rate on this page. Very small class; mathematical and games signal is the screen."
  },
  {
    id: "sig-qt-nyc", firm: "SIG", role_type: "QT", tier: 1, status: "open",
    firm_note: "Susquehanna. Screens hard on games and expected value.",
    title: "Quantitative Trader Internship",
    locations: ["New York"],
    apply_url: "https://careers.sig.com/quant-internships/jobs/10718?lang=en-us",
    eligibility_note: "Intend to graduate and begin full-time work by August 2028.",
    comp: "$7,600/wk + sign-on + housing", comp_source: "posted", comp_rank: 32900,
    multi_apply: "No restriction stated",
    notes: "Highest weekly rate on this page. Ten-week program. Lean into poker and expected value."
  },
  {
    id: "jump-qt", firm: "Jump Trading", role_type: "QT", tier: 1, status: "open",
    title: "Campus Quantitative Trader (Intern)",
    locations: ["Chicago", "New York"],
    apply_url: "https://www.jumptrading.com/hr/job?gh_jid=7848371",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "",
    notes: "Jump also runs a separate undergraduate QR seat; both are on the same board."
  },
  {
    id: "tower-qt", firm: "Tower Research", role_type: "QT", tier: 1, status: "open",
    title: "Quantitative Trader Intern",
    locations: ["New York", "Chicago"],
    apply_url: "https://www.tower-research.com/open-positions/?gh_jid=8024128",
    eligibility_note: "",
    comp: "$3,500–$5,700/wk + housing", comp_source: "posted", comp_rank: 19900,
    multi_apply: "No policy stated",
    notes: "More coding- and modeling-heavy than some trader loops."
  },
  {
    id: "opt-qt", firm: "Optiver", role_type: "QT", tier: 1, status: "open",
    title: "Quantitative Intern",
    locations: ["Chicago", "Austin"],
    apply_url: "https://www.optiver.com/join-us/jobs/institutional-sales-and-trading/chicago/quantitative-intern-summer-2027/",
    eligibility_note: "December 2027 to June 2029, sophomore standing or higher.",
    comp: "$70,000–$88,000 + flights & housing", comp_source: "posted", comp_rank: 20000,
    multi_apply: "Combined trading/research funnel",
    notes: "One application covers both sides. Note Optiver's global re-apply cooldown after a failed assessment."
  },
  {
    id: "sig-qt-chi", firm: "SIG", role_type: "QT", tier: 1, status: "open",
    title: "Quantitative Trader Internship",
    locations: ["Chicago"],
    apply_url: "https://careers.sig.com/quantitative-trading-internships-co-ops/jobs/10849",
    eligibility_note: "Intend to graduate and begin full-time work by August 2028.",
    comp: "$7,600/wk + sign-on + housing", comp_source: "posted", comp_rank: 32900,
    multi_apply: "No restriction stated",
    notes: "Same loop as the NYC posting, different office. A Bala Cynwyd (Philadelphia) req also exists."
  },

  /* — tier 2 — */
  {
    id: "flow-qt", firm: "Flow Traders", role_type: "QT", tier: 2, status: "open",
    title: "Quantitative Trading Intern",
    locations: ["New York"],
    apply_url: "https://www.flowtraders.com/careers/job-description/8047166",
    eligibility_note: "Class of 2028 preferred; December 2027 to June 2029 accepted.",
    comp: "$150,000 prorated base", comp_source: "posted", comp_rank: 12500,
    multi_apply: "No restriction stated",
    notes: "Says 'Class of 2028 preferred', so you are the target. Screens written answers for AI-generated text."
  },
  {
    id: "imc-qt", firm: "IMC Trading", role_type: "QT", tier: 2, status: "open",
    title: "Quantitative Trader Intern",
    locations: ["Chicago"],
    apply_url: "https://www.imc.com/us/careers/jobs/4823923101",
    eligibility_note: "Graduating September 2027 to July 2028.",
    comp: "$250,000 annualized base", comp_source: "posted", comp_rank: 20833,
    multi_apply: "One per role, one best fit urged", one_only: true,
    notes: "One application per role per year, and IMC strongly encourages focusing on a single best fit."
  },
  {
    id: "drw-qt", firm: "DRW", role_type: "QT", tier: 2, status: "open",
    title: "Quantitative Trading Analyst Intern",
    locations: ["Chicago"],
    apply_url: "https://www.drw.com/work-at-drw/listings/quantitative-trading-analyst-intern-3375090",
    eligibility_note: "Expected graduation December 2027 to June 2028.",
    // Two DRW reqs carry different posted ranges: the current listing reads $250,000
    // annualized, an older req read $175,000-$200,000. Verify on the live page.
    comp: "$250,000 annualized base", comp_source: "posted", comp_rank: 20833,
    multi_apply: "No restriction stated",
    notes: "DRW's trading seat, separate from its research intern req. Both may be applied to."
  },
  {
    id: "virtu-qt", firm: "Virtu Financial", role_type: "QT", tier: 2, status: "open",
    title: "2027 Internship, Quantitative Trading",
    locations: ["New York", "Chicago", "Austin"],
    apply_url: "https://job-boards.greenhouse.io/virtu/jobs/8624408002",
    eligibility_note: "Rising juniors, or ready for full-time work December 2027 to June 2028.",
    comp: "$5,000–$5,800/wk", comp_source: "posted", comp_rank: 23400,
    multi_apply: "One application only", one_only: true,
    notes: "Posting: 'Please only apply to one internship position.' Choose between this and the Virtu QR seat."
  },
  {
    id: "ctc-qt", firm: "Chicago Trading Co.", role_type: "QT", tier: 2, status: "open",
    title: "Quant Trading Internship",
    locations: ["Chicago"],
    apply_url: "https://job-boards.greenhouse.io/ctccampusboard/jobs/4708188005",
    eligibility_note: "Graduating December 2027 to June 2028. All majors welcome.",
    comp: "$14,500/mo + sign-on + free housing", comp_source: "posted", comp_rank: 14500,
    multi_apply: "One application per position",
    notes: "Eight weeks, mid-June to early August. Posting warns applications may be AI-screened."
  },
  {
    id: "aqr-qt", firm: "AQR Capital", role_type: "QT", tier: 2, status: "open",
    title: "2027 Trading Summer Analyst",
    locations: ["Greenwich, CT"],
    apply_url: "https://careers.aqr.com/jobs?gh_jid=8077110",
    eligibility_note: "Graduating between December 2027 and June 2028.",
    comp: "~$60–63/hr", comp_source: "reported", comp_rank: 10600,
    multi_apply: "No limit; nine separate 2027 reqs",
    notes: "Commutable from NYC via Metro-North. Grad window fits May 2028 exactly."
  },

  /* — tier 3 — */
  {
    id: "tmg-qt", firm: "TransMarket Group", role_type: "QT", tier: 3, status: "open",
    title: "Quantitative Trader Intern",
    locations: ["Chicago"],
    apply_url: "https://job-boards.greenhouse.io/transmarketgroup/jobs/5151569007",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No policy stated",
    notes: ""
  },
  {
    id: "trlm-qt", firm: "Trillium", role_type: "QT", tier: 3, status: "open",
    title: "Summer 2027 Equity Trader Internship",
    locations: ["New York", "Chicago", "Miami"],
    apply_url: "https://www.trlm.com/apply/5076003007?gh_jid=5076003007",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No policy stated",
    notes: "Proprietary equity trading. NYC-headquartered, so no relocation."
  },
  {
    id: "blackedge-qt", firm: "BlackEdge Capital", role_type: "QT", tier: 3, status: "open",
    title: "Quantitative Trader Intern",
    locations: ["Chicago"],
    apply_url: "https://job-boards.greenhouse.io/blackedgecapital/jobs/4703820005",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No policy stated",
    notes: ""
  },
  {
    id: "g1-qt", firm: "Group One Trading", role_type: "QT", tier: 3, status: "open",
    title: "Trading Analyst Intern",
    locations: ["Chicago"],
    apply_url: "https://group1.applicantpro.com/jobs/3859850",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "",
    notes: "Options market maker. Listing found on their ATS rather than a campus page; verify before relying on it."
  },

  /* ════ QUANTITATIVE RESEARCH ═════════════════════════════════ */

  /* — tier 1 — */
  {
    id: "js-qr", firm: "Jane Street", role_type: "QR", tier: 1, status: "open",
    title: "Quantitative Researcher Internship (May–August)",
    locations: ["New York"],
    apply_url: "https://www.janestreet.com/join-jane-street/position/8498547002/",
    eligibility_note: "Most interns are current undergraduates or graduate students.",
    comp: "$300,000 annualized base", comp_source: "posted", comp_rank: 25000,
    multi_apply: "Multiple allowed",
    notes: "Separate posting from the trader role; both may be submitted."
  },
  {
    id: "des-qr", firm: "D. E. Shaw", role_type: "QR", tier: 1, status: "open",
    title: "Quantitative Analyst Intern",
    locations: ["New York"],
    apply_url: "https://www.deshaw.com/careers/quantitative-analyst-intern-new-york-summer-2027-5890",
    eligibility_note: "Enrolled full-time, usually approaching the final year. Non-PhD track.",
    comp: "$25,000/mo + $25,000 sign-on + housing", comp_source: "posted", comp_rank: 25000,
    multi_apply: "Bundle several roles in one application",
    notes: "Largest posted sign-on here. Bundle with the Proprietary Trading req."
  },
  {
    id: "hrt-qr", firm: "Hudson River Trading", role_type: "QR", tier: 1, status: "open",
    title: "Algorithm Development (Quant Research & Trading) Internship",
    locations: ["New York", "Singapore"],
    apply_url: "https://www.hudsonrivertrading.com/hrt-job/algorithm-development-quant-research-internship-summer-2027/",
    eligibility_note: "Full-time undergraduate or master's student in a quantitative discipline.",
    // The $5,800 figure is verbatim from HRT's Summer 2026 req; the 2027 posting's
    // compensation block would not render on fetch. Labelled accordingly.
    comp: "$5,800/wk + $25,000 sign-on", comp_source: "posted, 2026 cycle", comp_rank: 25100,
    multi_apply: "One application only", one_only: true,
    notes: "Posting is explicit: 'We do not allow multiple applications.' Python/C++, modeling, trading research."
  },
  {
    id: "cits-qr", firm: "Citadel Securities", role_type: "QR", tier: 1, status: "open",
    title: "Quantitative Research Analyst Intern (BS/MS)",
    locations: ["New York", "Miami"],
    // The "-bs-ms-" variant a research pass suggested is a 404; this is the live URL.
    apply_url: "https://www.citadelsecurities.com/careers/details/quantitative-research-analyst-intern-us/",
    eligibility_note: "Bachelor's or master's in a highly quantitative field.",
    comp: "$4,500–$5,800/wk + sign-on + housing", comp_source: "posted", comp_rank: 22300,
    multi_apply: "Not stated",
    notes: "The undergraduate-eligible QR seat. The PhD reqs are a separate pipeline."
  },
  {
    id: "ts-qr", firm: "Two Sigma", role_type: "QR", tier: 1, status: "open",
    title: "Quantitative Researcher, Intern",
    locations: ["New York"],
    apply_url: "https://careers.twosigma.com/careers/JobDetail/New-York-New-York-United-States-Quantitative-Researcher-Intern-2027-Summer/13945",
    eligibility_note: "Pursuing a technical or quantitative degree. Bachelor's track explicitly priced.",
    comp: "$4,900/wk (Bachelor's)", comp_source: "posted", comp_rank: 21200,
    multi_apply: "No limit stated",
    notes: "The AI Research Scientist req at the same firm is MS/PhD only; this one is not."
  },
  {
    id: "js-qr-ml", firm: "Jane Street", role_type: "QR", tier: 1, status: "open",
    title: "Quantitative Research (Machine Learning) Internship",
    locations: ["New York"],
    apply_url: "https://www.janestreet.com/join-jane-street/position/8384490002/",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "Multiple allowed",
    notes: "The ML track, if the XGBoost and state-space work is the story you want to tell."
  },
  {
    id: "jump-qr", firm: "Jump Trading", role_type: "QR", tier: 1, status: "open",
    title: "Campus Quantitative Researcher, UG/MS (Intern)",
    locations: ["Chicago", "New York"],
    apply_url: "https://www.jumptrading.com/hr/job?gh_jid=7982648",
    eligibility_note: "Title is explicitly UG/MS. No graduation window stated.",
    comp: "$300,000 annualized base", comp_source: "posted", comp_rank: 25000,
    multi_apply: "No restriction stated",
    notes: "The rate is an annualized figure printed on a ten-week req, so roughly $5,800/wk in practice."
  },

  /* — tier 2 — */
  {
    id: "sqp-qr", firm: "Squarepoint", role_type: "QR", tier: 2, status: "open",
    title: "Intern Quant Researcher",
    locations: ["New York", "London", "Paris"],
    apply_url: "https://www.squarepoint-capital.com/open-opportunities?id=243853&gh_jid=243853",
    eligibility_note: "No graduation window stated. Quantitative degree required.",
    comp: "$150,000 min base (NY)", comp_source: "posted", comp_rank: 12500,
    multi_apply: "One application only", one_only: true,
    notes: "Posting opens in bold: apply only to the one job you feel best fits."
  },
  {
    id: "bw-qr", firm: "Bridgewater", role_type: "QR", tier: 2, status: "open",
    title: "2027 Investment Associate Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/bridgewater89/jobs/8395041002",
    eligibility_note: "No graduation window stated anywhere in the posting.",
    comp: "$71,000 for 8 weeks + housing", comp_source: "posted", comp_rank: 38000,
    multi_apply: "One consolidated application",
    notes: "Bridgewater merged its two former application routes into one."
  },
  {
    id: "drw-qr", firm: "DRW", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Research Intern",
    locations: ["Chicago", "New York"],
    apply_url: "https://www.drw.com/work-at-drw/listings/quantitative-research-intern-3413670",
    eligibility_note: "Expected graduation December 2027 to June 2028.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No restriction stated",
    notes: "Probability, logic, Python and market reasoning. Pairs with the DRW trading seat."
  },
  {
    id: "virtu-qr", firm: "Virtu Financial", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Research Intern (Undergraduate)",
    locations: ["New York", "Austin"],
    apply_url: "https://job-boards.greenhouse.io/virtu/jobs/8142539002",
    eligibility_note: "Explicitly the undergraduate track. Ready for full-time work Dec 2027 to June 2028.",
    comp: "$5,000–$5,800/wk", comp_source: "posted", comp_rank: 23400,
    multi_apply: "One application only", one_only: true,
    notes: "Competes with the Virtu QT seat for your single Virtu application. Programming gate."
  },
  {
    id: "imc-qr", firm: "IMC Trading", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Researcher Intern (BS/MS)",
    locations: ["Chicago"],
    apply_url: "https://www.imc.com/us/careers/jobs/4907399101",
    eligibility_note: "Graduating September 2027 to July 2028. Bachelor's or Master's track.",
    comp: "$250,000 annualized base", comp_source: "posted", comp_rank: 20833,
    multi_apply: "One per role, one best fit urged", one_only: true,
    notes: "Competes with the IMC QT seat for your best-fit application."
  },
  {
    id: "arrow-qr", firm: "Arrowstreet Capital", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Researcher Intern",
    locations: ["Boston"],
    apply_url: "https://arrowstreetcapital.wd5.myworkdayjobs.com/Campus_Careers",
    eligibility_note: "Enrolled in an undergraduate or graduate program.",
    comp: "$3,500–$5,000/wk", comp_source: "posted", comp_rank: 18400,
    multi_apply: "No restriction stated",
    notes: "Only two 2027 intern reqs on the campus board, QR and QD."
  },
  {
    id: "akuna-qr", firm: "Akuna Capital", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Research Intern",
    locations: ["Chicago"],
    apply_url: "https://www.akunacapital.com/careers/job/8036614/?gh_jid=8036614",
    eligibility_note: "",
    comp: "$145,000 min annualized", comp_source: "posted", comp_rank: 12083,
    multi_apply: "One application only", one_only: true,
    notes: "Applying signals this is your top Akuna preference; you will not be considered for the others."
  },
  {
    id: "aqr-qr", firm: "AQR Capital", role_type: "QR", tier: 2, status: "open",
    title: "2027 Research Summer Analyst",
    locations: ["Greenwich, CT"],
    apply_url: "https://careers.aqr.com/jobs/open-positions/greenwich-ct/2027-research-summer-analyst/7895583?gh_jid=7895583",
    eligibility_note: "December 2027 or spring 2028 graduate in a quantitative field.",
    comp: "~$60–63/hr", comp_source: "reported", comp_rank: 10600,
    multi_apply: "No limit; nine separate 2027 reqs",
    notes: "Commutable from NYC."
  },
  {
    id: "aqr-qr-pi", firm: "AQR Capital", role_type: "QR", tier: 2, status: "open",
    title: "2027 Portfolio Implementation Summer Analyst",
    locations: ["Greenwich, CT"],
    apply_url: "https://careers.aqr.com/jobs?gh_jid=7895562",
    eligibility_note: "December 2027 or spring 2028 graduate in a quantitative field.",
    comp: "~$60–63/hr", comp_source: "reported", comp_rank: 10600,
    multi_apply: "No limit; nine separate 2027 reqs",
    notes: "Closer to execution and portfolio construction than pure signal research."
  },
  {
    id: "aquatic-qr", firm: "Aquatic Capital", role_type: "QR", tier: 2, status: "open",
    title: "Quantitative Researcher, Intern",
    locations: ["Chicago", "London"],
    apply_url: "https://job-boards.greenhouse.io/aquaticcapitalmanagement/jobs/8489186002",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No restriction stated",
    notes: ""
  },

  /* — tier 3 — */
  {
    id: "wal-ceqr", firm: "Walleye Capital", role_type: "QR", tier: 3, status: "open",
    title: "Central Equity Quant Research (CEQR) Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4676069006",
    eligibility_note: "",
    comp: "$20,000/mo + $10,000 housing", comp_source: "posted", comp_rank: 20000,
    multi_apply: "Not covered by the Quantic limit",
    notes: "Best-paid NYC seat outside the top tier. The one-of-three rule applies only to Quantic roles."
  },
  {
    id: "seven-qr", firm: "Seven Research", role_type: "QR", tier: 3, status: "open",
    title: "Quantitative Researcher, Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/sevenresearch/jobs/4894946008",
    eligibility_note: "",
    comp: "Prorated from $200–300k base", comp_source: "posted", comp_rank: 20800,
    multi_apply: "No policy stated",
    notes: ""
  },
  {
    id: "wal-ids", firm: "Walleye Capital", role_type: "QR", tier: 3, status: "open",
    title: "Investment Data Science Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4676587006",
    eligibility_note: "",
    comp: "$14,000/mo + $10,000 housing", comp_source: "posted", comp_rank: 14000,
    multi_apply: "No restriction stated",
    notes: ""
  },
  {
    id: "quantic-qr", firm: "Quantic", role_type: "QR", tier: 3, status: "open",
    firm_note: "Walleye's Boston quant arm; recruits on the Walleye students board.",
    title: "Quantic Quantitative Researcher Intern",
    locations: ["Boston"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4679173006",
    eligibility_note: "",
    comp: "$20,000/mo + $10,000 housing", comp_source: "posted", comp_rank: 20000,
    multi_apply: "One of the three Quantic roles only", one_only: true,
    notes: "Apply to exactly one of Quantic QR, Quantic QD or the Quantic PhD QR."
  },
  {
    id: "wal-vol", firm: "Walleye Capital", role_type: "QR", tier: 3, status: "open",
    title: "Equity Volatility Quant Researcher Intern",
    locations: ["Miami"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4676334006",
    eligibility_note: "",
    comp: "$50,000/10 wks + $10,000 housing", comp_source: "posted", comp_rank: 21600,
    multi_apply: "No restriction stated",
    notes: "Volatility desk. Financial Derivatives coursework is directly relevant."
  },
  {
    id: "anth-qr", firm: "Anthelion Capital", role_type: "QR", tier: 3, status: "open",
    title: "Quant Research / Quant Developer Intern",
    locations: ["New York"],
    apply_url: "https://jobs.ashbyhq.com/anthelioncap/5e2ea37b-2369-474e-b717-c24c60976e96",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No policy stated",
    notes: "Small Midtown shop, onsite. One combined research/development req."
  },
  {
    id: "volo-qr", firm: "Voloridge", role_type: "QR", tier: 3, status: "open",
    title: "Quantitative Research Intern",
    locations: ["Jupiter, FL"],
    apply_url: "https://job-boards.greenhouse.io/voloridgeinvestmentmanagement/jobs/4226247009",
    eligibility_note: "At least three years of an undergraduate degree completed.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No restriction stated",
    notes: "Florida only. Strong systematic shop, but relocation is the cost."
  },

  /* ════ QUANTITATIVE DEVELOPMENT ══════════════════════════════ */
  {
    id: "tower-qd", firm: "Tower Research", role_type: "QD", tier: 1, status: "open",
    title: "Quantitative Developer Intern",
    locations: ["New York", "Chicago"],
    apply_url: "https://www.tower-research.com/open-positions/?gh_jid=8044334",
    eligibility_note: "",
    comp: "$3,500–$5,700/wk + housing", comp_source: "posted", comp_rank: 19900,
    multi_apply: "No policy stated",
    notes: "No stated restriction, so this and the Tower QT seat can both be applied to."
  },
  {
    id: "akuna-qd", firm: "Akuna Capital", role_type: "QD", tier: 2, status: "open",
    title: "Quantitative Development & Strategy Intern",
    locations: ["Chicago"],
    apply_url: "https://www.akunacapital.com/careers/job/8021481/?gh_jid=8021481",
    eligibility_note: "",
    comp: "$145,000 min annualized", comp_source: "posted", comp_rank: 12083,
    multi_apply: "One application only", one_only: true,
    notes: "Same hard restriction as the Akuna QR req. Pick one."
  },
  {
    id: "radix-qd", firm: "Radix Trading", role_type: "QD", tier: 2, status: "open",
    title: "Quantitative Technologist (C++ Intern)",
    locations: ["Chicago"],
    apply_url: "https://job-boards.greenhouse.io/radixuniversity/jobs/8500265002",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "One application only", one_only: true,
    notes: "C++ heavy. Posting says apply to only one Radix job."
  },
  {
    id: "aqr-qd", firm: "AQR Capital", role_type: "QD", tier: 2, status: "open",
    title: "2027 Research and Portfolio Management Engineering Summer Analyst",
    locations: ["Greenwich, CT"],
    apply_url: "https://careers.aqr.com/jobs?gh_jid=7957728",
    eligibility_note: "Bachelor's or Master's finishing December 2027 to June 2028.",
    comp: "~$60–63/hr", comp_source: "reported", comp_rank: 10600,
    multi_apply: "No limit; nine separate 2027 reqs",
    notes: ""
  },
  {
    id: "wal-vtd", firm: "Walleye Capital", role_type: "QD", tier: 3, status: "open",
    title: "Volatility Trading Developer Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4679434006",
    eligibility_note: "",
    comp: "$14,000/mo + $10,000 housing", comp_source: "posted", comp_rank: 14000,
    multi_apply: "No restriction stated",
    notes: ""
  },
  {
    id: "seven-qd", firm: "Seven Research", role_type: "QD", tier: 3, status: "open",
    title: "Algorithmic Developer, Intern",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/sevenresearch/jobs/4895082008",
    eligibility_note: "",
    comp: "Prorated from $200–300k base", comp_source: "posted", comp_rank: 20800,
    multi_apply: "No policy stated",
    notes: ""
  },
  {
    id: "quantic-qd", firm: "Quantic", role_type: "QD", tier: 3, status: "open",
    title: "Quantic Quantitative Developer Intern",
    locations: ["Boston"],
    apply_url: "https://job-boards.greenhouse.io/walleyecapital-external-students/jobs/4679168006",
    eligibility_note: "",
    comp: "$20,000/mo + $10,000 housing", comp_source: "posted", comp_rank: 20000,
    multi_apply: "One of the three Quantic roles only", one_only: true,
    notes: "Given QR outranks QD for you, the Quantic QR seat is the better use of that single application."
  },
  {
    id: "blackedge-qd", firm: "BlackEdge Capital", role_type: "QD", tier: 3, status: "open",
    title: "Quantitative Developer Intern",
    locations: ["Chicago"],
    apply_url: "https://job-boards.greenhouse.io/blackedgecapital/jobs/4703821005",
    eligibility_note: "",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No policy stated",
    notes: ""
  },
  {
    id: "volo-qd", firm: "Voloridge", role_type: "QD", tier: 3, status: "open",
    title: "Quantitative Developer Intern",
    locations: ["Jupiter, FL"],
    apply_url: "https://job-boards.greenhouse.io/voloridgeinvestmentmanagement/jobs/4224862009",
    eligibility_note: "Pursuing a Bachelor's, Master's or PhD in Computer Science or related.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "No restriction stated",
    notes: ""
  },

  /* ════ NOT OPEN YET ══════════════════════════════════════════ */
  {
    id: "mlp-soon", firm: "Millennium", role_type: "QT", tier: 1, status: "soon",
    opens: "3 Aug",
    firm_note: "2027 program applications open 3 August 2026.",
    title: "2027 Internship Program (quant tracks)",
    locations: ["New York"],
    apply_url: "https://mlp.com/careers/students/",
    eligibility_note: "US quant reqs not yet posted; board currently shows non-US roles only.",
    comp: "$175,000–$180,000 annualized", comp_source: "reported", comp_rank: 14800,
    multi_apply: "Two applications maximum, across all locations", one_only: true,
    notes: "Diarise this. The two-application cap means role and city must be chosen deliberately."
  },
  {
    id: "bam-soon", firm: "Balyasny", role_type: "QR", tier: 2, status: "soon",
    opens: "~Aug",
    title: "Quantitative Analyst Internship",
    locations: ["New York", "Chicago"],
    apply_url: "https://bamfunds.com/careers/internships/",
    eligibility_note: "Live listings still carry the prior cycle's window; Summer 2027 not yet posted.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "",
    notes: "Secondary sources point to a late-July or August opening. Check weekly."
  },
  {
    id: "wolv-soon", firm: "Wolverine Trading", role_type: "QT", tier: 2, status: "soon",
    opens: "~Aug",
    title: "Quantitative Trading / Research Internship",
    locations: ["Chicago"],
    apply_url: "https://careers.wolve.com/",
    eligibility_note: "Board fully enumerated 30 July 2026: 15 live roles, all experienced-hire.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "",
    notes: "Runs a summer program historically. Timing gap, not an absence."
  },
  {
    id: "belv-soon", firm: "Belvedere Trading", role_type: "QT", tier: 3, status: "soon",
    opens: "~Aug",
    title: "Quantitative Trader / Researcher Internship",
    locations: ["Chicago"],
    apply_url: "https://belvederetrading.com/careers/",
    eligibility_note: "Lever board enumerated 30 July 2026: 10 live roles, none an internship.",
    comp: "~$78/hr", comp_source: "reported", comp_rank: 13500,
    multi_apply: "",
    notes: "Campus page says applications are reviewed on a rolling basis; summer reqs typically post in August."
  },
  {
    id: "schon-soon", firm: "Schonfeld", role_type: "QR", tier: 2, status: "soon",
    opens: "Autumn",
    title: "Summer Internship Program (quant tracks)",
    locations: ["New York"],
    apply_url: "https://job-boards.greenhouse.io/schonfeld",
    eligibility_note: "Program targets rising seniors, so structurally a fit once posted.",
    comp: "", comp_source: "", comp_rank: null,
    multi_apply: "",
    notes: "The 2027 interest form was removed in June 2026. Live board is 2026-cycle and non-US."
  },
  {
    id: "peak6-soon", firm: "PEAK6", role_type: "QT", tier: 3, status: "soon",
    opens: "~Aug",
    title: "Trading Bootcamp",
    locations: ["Chicago"],
    apply_url: "https://www.peak6.com/careers/",
    eligibility_note: "One week, not a full internship. Prior cycle required junior standing.",
    comp: "$25–31/hr", comp_source: "reported", comp_rank: 4800,
    multi_apply: "",
    notes: "A one-week micro-internship rather than a summer seat. Low cost, useful signal."
  }

];

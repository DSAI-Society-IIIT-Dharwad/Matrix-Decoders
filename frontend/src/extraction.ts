import type {
  DomainMode,
  ReviewFieldDefinition,
  SessionDetailResponse
} from "./types";

export const GENERIC_FIELDS: ReviewFieldDefinition[] = [
  {
    key: "complaint_query",
    label: "Complaint / Query",
    placeholder: "Primary issue or request from the conversation."
  },
  {
    key: "background_history",
    label: "Background History",
    placeholder: "Past context, history, or prior interaction details."
  },
  {
    key: "observations_responses",
    label: "Observations / Responses",
    placeholder: "Observed facts, user responses, or notable conversational evidence."
  },
  {
    key: "diagnosis_classification_status",
    label: "Diagnosis / Classification / Status",
    placeholder: "Current status, classification, or inferred assessment."
  },
  {
    key: "action_plan_treatment_plan",
    label: "Action Plan / Treatment Plan",
    placeholder: "Recommended next steps, treatment, or workflow actions."
  },
  {
    key: "verification_survey_responses",
    label: "Verification / Survey Responses",
    placeholder: "Verification points or survey-style answers from the interaction."
  }
];

export const DOMAIN_FIELDS: Record<DomainMode, ReviewFieldDefinition[]> = {
  healthcare: [
    { key: "symptoms", label: "Symptoms", placeholder: "Symptoms or complaints mentioned." },
    { key: "past_history", label: "Past History", placeholder: "Relevant past medical history." },
    {
      key: "clinical_observations",
      label: "Clinical Observations",
      placeholder: "Observed clinical findings or reported observations."
    },
    { key: "diagnosis", label: "Diagnosis", placeholder: "Diagnosis or likely assessment." },
    {
      key: "treatment_advice",
      label: "Treatment Advice",
      placeholder: "Medication, care plan, or follow-up advice."
    },
    {
      key: "immunization_data",
      label: "Immunization Data",
      placeholder: "Vaccination or immunization details."
    },
    {
      key: "pregnancy_data",
      label: "Pregnancy Data",
      placeholder: "Pregnancy-related details if present."
    },
    {
      key: "risk_indicators",
      label: "Risk Indicators",
      placeholder: "Risk indicators, warning signs, or escalation markers."
    },
    {
      key: "injury_mobility",
      label: "Injury & Mobility",
      placeholder: "Injury description or mobility-related information."
    },
    {
      key: "ent_findings",
      label: "ENT Findings",
      placeholder: "Ear, nose, throat findings if mentioned."
    }
  ],
  financial: [
    {
      key: "identity_verification",
      label: "Identity Verification",
      placeholder: "Identity verification or KYC confirmations."
    },
    {
      key: "account_loan_confirmation",
      label: "Account / Loan Confirmation",
      placeholder: "Account, policy, or loan confirmation details."
    },
    {
      key: "payment_status",
      label: "Payment Status",
      placeholder: "Payment completion, due status, or delinquency details."
    },
    {
      key: "payer_identity",
      label: "Payer Identity",
      placeholder: "Who made or will make the payment."
    },
    {
      key: "payment_date",
      label: "Payment Date",
      placeholder: "Payment date, due date, or collection date."
    },
    {
      key: "payment_mode",
      label: "Payment Mode",
      placeholder: "Cash, UPI, bank transfer, card, or related payment mode."
    },
    {
      key: "executive_interaction_details",
      label: "Executive Interaction Details",
      placeholder: "Agent or executive interaction details."
    },
    {
      key: "reason_for_payment",
      label: "Reason for Payment",
      placeholder: "Reason given for payment or non-payment."
    },
    {
      key: "amount_paid",
      label: "Amount Paid",
      placeholder: "Amount collected or payment amount discussed."
    }
  ]
};

type DeriveInput = {
  domain: DomainMode;
  snapshot: SessionDetailResponse | null;
  uploadedTranscript?: string;
  liveTranscript?: string;
  latestAssistant?: string;
  assistantDraft?: string;
};

function cleanText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function splitSentences(text: string): string[] {
  return cleanText(text)
    .split(/(?<=[.!?])\s+|\n+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = cleanText(value);
    if (!normalized || seen.has(normalized.toLowerCase())) {
      continue;
    }
    seen.add(normalized.toLowerCase());
    output.push(normalized);
  }
  return output;
}

function firstNonEmpty(...values: Array<string | undefined>): string {
  for (const value of values) {
    const normalized = cleanText(value || "");
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function extractByKeywords(sentences: string[], keywords: string[]): string {
  const lowerKeywords = keywords.map((keyword) => keyword.toLowerCase());
  const matches = sentences.filter((sentence) => {
    const lower = sentence.toLowerCase();
    return lowerKeywords.some((keyword) => lower.includes(keyword));
  });
  return unique(matches).join(" ");
}

function collectConversation(input: DeriveInput) {
  const userMessages =
    input.snapshot?.messages
      .filter((message) => message.role === "user")
      .map((message) => message.content) || [];
  const assistantMessages =
    input.snapshot?.messages
      .filter((message) => message.role === "assistant")
      .map((message) => message.content) || [];
  const transcripts = input.snapshot?.transcripts.map((record) => record.text) || [];

  if (input.uploadedTranscript) {
    transcripts.push(input.uploadedTranscript);
  }
  if (input.liveTranscript) {
    transcripts.push(input.liveTranscript);
  }
  if (input.latestAssistant) {
    assistantMessages.push(input.latestAssistant);
  }
  if (input.assistantDraft) {
    assistantMessages.push(input.assistantDraft);
  }

  return {
    userMessages: unique(userMessages),
    assistantMessages: unique(assistantMessages),
    transcripts: unique(transcripts)
  };
}

export function deriveStructuredReport(input: DeriveInput): Record<string, string> {
  const conversation = collectConversation(input);
  const userText = conversation.userMessages.join(" ");
  const assistantText = conversation.assistantMessages.join(" ");
  const transcriptText = conversation.transcripts.join(" ");
  const allSentences = splitSentences([userText, transcriptText, assistantText].join(" "));
  const assistantSentences = splitSentences(assistantText);
  const transcriptSentences = splitSentences(transcriptText);
  const userSentences = splitSentences(userText);

  const report: Record<string, string> = {
    complaint_query: firstNonEmpty(transcriptSentences[0], userSentences[0], transcriptText, userText),
    background_history: extractByKeywords(allSentences, [
      "history",
      "background",
      "past",
      "previous",
      "before",
      "earlier",
      "since"
    ]),
    observations_responses: firstNonEmpty(
      extractByKeywords(transcriptSentences, [
        "response",
        "responded",
        "reports",
        "reported",
        "states",
        "mentioned",
        "complains",
        "asks",
        "needs"
      ]),
      transcriptSentences.slice(0, 3).join(" ")
    ),
    diagnosis_classification_status: firstNonEmpty(
      extractByKeywords(assistantSentences, [
        "diagnosis",
        "status",
        "classification",
        "assessment",
        "classified",
        "likely",
        "appears",
        "confirmed",
        "pending",
        "resolved",
        "due"
      ]),
      assistantSentences[0]
    ),
    action_plan_treatment_plan: extractByKeywords(assistantSentences, [
      "plan",
      "next step",
      "should",
      "recommend",
      "advice",
      "treatment",
      "follow up",
      "action",
      "prescribe",
      "schedule",
      "please"
    ]),
    verification_survey_responses: extractByKeywords(allSentences, [
      "confirm",
      "verified",
      "verification",
      "survey",
      "yes",
      "no",
      "account",
      "loan",
      "identity",
      "payment"
    ])
  };

  if (input.domain === "healthcare") {
    report.symptoms = extractByKeywords(allSentences, [
      "symptom",
      "pain",
      "fever",
      "cough",
      "headache",
      "vomit",
      "nausea",
      "fatigue",
      "breath",
      "swelling"
    ]);
    report.past_history = extractByKeywords(allSentences, [
      "history",
      "surgery",
      "allergy",
      "chronic",
      "diabetes",
      "hypertension",
      "asthma",
      "previous"
    ]);
    report.clinical_observations = extractByKeywords(allSentences, [
      "observation",
      "exam",
      "observed",
      "clinical",
      "vitals",
      "temperature",
      "blood pressure",
      "pulse"
    ]);
    report.diagnosis = extractByKeywords(assistantSentences, [
      "diagnosis",
      "likely",
      "assessment",
      "condition",
      "infection",
      "injury"
    ]);
    report.treatment_advice = extractByKeywords(assistantSentences, [
      "treatment",
      "advice",
      "medication",
      "tablet",
      "rest",
      "hydrate",
      "follow up",
      "consult"
    ]);
    report.immunization_data = extractByKeywords(allSentences, [
      "vaccine",
      "vaccination",
      "immunization",
      "booster"
    ]);
    report.pregnancy_data = extractByKeywords(allSentences, [
      "pregnancy",
      "pregnant",
      "trimester",
      "antenatal"
    ]);
    report.risk_indicators = extractByKeywords(allSentences, [
      "risk",
      "warning",
      "red flag",
      "danger",
      "severe",
      "urgent"
    ]);
    report.injury_mobility = extractByKeywords(allSentences, [
      "injury",
      "fall",
      "fracture",
      "mobility",
      "walking",
      "movement",
      "limp"
    ]);
    report.ent_findings = extractByKeywords(allSentences, [
      "ear",
      "nose",
      "throat",
      "sinus",
      "hearing",
      "swallow"
    ]);
  } else {
    report.identity_verification = extractByKeywords(allSentences, [
      "identity",
      "verify",
      "verified",
      "kyc",
      "aadhaar",
      "pan"
    ]);
    report.account_loan_confirmation = extractByKeywords(allSentences, [
      "account",
      "loan",
      "policy",
      "statement",
      "reference number",
      "customer id"
    ]);
    report.payment_status = extractByKeywords(allSentences, [
      "payment",
      "paid",
      "due",
      "overdue",
      "pending",
      "settled"
    ]);
    report.payer_identity = extractByKeywords(allSentences, [
      "payer",
      "customer",
      "borrower",
      "account holder",
      "paid by"
    ]);
    report.payment_date = extractByKeywords(allSentences, [
      "today",
      "tomorrow",
      "date",
      "due date",
      "payment date",
      "on monday",
      "on tuesday"
    ]);
    report.payment_mode = extractByKeywords(allSentences, [
      "upi",
      "cash",
      "transfer",
      "bank",
      "cheque",
      "card",
      "mode"
    ]);
    report.executive_interaction_details = extractByKeywords(allSentences, [
      "executive",
      "agent",
      "collector",
      "representative",
      "called",
      "spoke"
    ]);
    report.reason_for_payment = extractByKeywords(allSentences, [
      "reason",
      "because",
      "salary",
      "delay",
      "issue",
      "paid for"
    ]);
    report.amount_paid = extractByKeywords(allSentences, [
      "rupees",
      "amount",
      "paid",
      "rs",
      "₹"
    ]);
  }

  return report;
}

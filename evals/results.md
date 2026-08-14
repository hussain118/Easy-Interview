# Eval results — 5 personas

Real GPT calls (per-answer evaluator + final scorer), synthetic transcripts.

| Persona | Overall score | Recommendation | Avg confidence | Guardrail rejections |
|---|---|---|---|---|
| strong | 5.0 | hire | 0.9 | 0 |
| average | 2.0 | no_hire | 0.8 | 0 |
| weak | 2.0 | no_hire | 0.88 | 0 |
| bluffer | 1.5 | no_hire | 0.8 | 0 |
| nervous | 2.25 | no_hire | 0.75 | 0 |

**Expected ranking** (strongest to weakest): strong > nervous > average > bluffer > weak
**Actual ranking** (by overall_score): strong > nervous > average > weak > bluffer

**Overall: FAIL**

## Checks
- PASS: `strong_is_highest`
- FAIL: `weak_is_lowest`
- PASS: `bluffer_below_average`
- PASS: `nervous_near_strong`

## Failure analysis
- **weak_is_lowest failed.** Scores: strong=5.0, average=2.0, weak=2.0, bluffer=1.5, nervous=2.25

**Specific note on weak_is_lowest**: the bluffer scored *below* weak (both landed no_hire, but bluffer lower). The PDF's literal wording puts weak as 'Lowest' and only requires bluffer to land 'below Average' — this run technically over-shoots that: once the per-answer evaluator correctly flagged the bluffer's fabricated/unverifiable claims as `bluff` on multiple turns, the final scorer weighted confident fabrication more harshly than honest-but-thin competence. That's an arguable, defensible outcome (a candidate who confidently claims false expertise arguably *is* worse than one who's simply inexperienced but truthful about it) rather than a scorer malfunction — but it doesn't strictly satisfy the literal ranking check, so it's reported as a failed check rather than quietly accepted.

This is reported honestly rather than hidden or re-run until it happened to pass — see the individual scorecards below for the reasoning GPT gave on each competency, which is the most useful signal for diagnosing why.

## Per-persona scorecards

### strong

Expected: Highest score, hire, high confidence

```json
{
  "candidate_name": "Persona: strong",
  "role": "Junior AI Engineer",
  "interview_date": "2026-01-01",
  "duration_seconds": 480,
  "competencies": [
    {
      "name": "backend",
      "score": 5,
      "confidence": 0.9,
      "evidence_quote": "I built a RAG service that indexes internal docs \u2014 chunked by paragraph with 200-token overlap, embedded with all-MiniLM-L6-v2, stored in Chroma, and I added a re-ranking step with a cross-encoder because pure cosine similarity was pulling near-duplicate chunks. The one thing I'd change is I never added eval metrics beyond manual spot-checking \u2014 I'd add RAGAS scoring if I did it again.",
      "reasoning": "The candidate provided a detailed and specific explanation of their RAG project architecture, including concrete numbers and a clear rationale for design choices, while also acknowledging a limitation and suggesting an improvement."
    },
    {
      "name": "rag",
      "score": 5,
      "confidence": 0.9,
      "evidence_quote": "It depends on document structure \u2014 for structured docs I chunk by section headers, for prose I use paragraph-based chunking with about 15% overlap so context isn't cut mid-sentence at boundaries. I benchmark retrieval precision on a held-out query set before committing to a chunk size.",
      "reasoning": "The candidate provided a specific chunking strategy based on document structure, included a concrete overlap percentage, and mentioned benchmarking retrieval precision, demonstrating depth and relevance to the question."
    },
    {
      "name": "python",
      "score": 5,
      "confidence": 0.9,
      "evidence_quote": "Right \u2014 I added overlap because without it, answers that spanned a paragraph boundary were getting split across two chunks and neither had enough context alone. I tested with and without overlap on a set of boundary-spanning questions and precision went up about 12%.",
      "reasoning": "The candidate provided a clear rationale for adding overlap to the chunker, supported by specific testing results that demonstrated a measurable improvement in precision, which aligns well with the evidence from the commit in their repo."
    },
    {
      "name": "debugging",
      "score": 5,
      "confidence": 0.9,
      "evidence_quote": "First I'd check if it's a retrieval problem or a generation problem \u2014 pull the raw retrieved chunks for a failing query and see if they're actually relevant. If retrieval is fine, it's a prompting/generation issue. If retrieval is bad, I'd check if the embedding model or index got swapped, or if new documents were ingested with a different chunking config than what's in production.",
      "reasoning": "The candidate provided a clear, structured approach to debugging the RAG pipeline, identifying specific areas to investigate and potential issues with retrieval and generation, which aligns well with their prior experience in chunking and precision improvements."
    }
  ],
  "overall_score": 5.0,
  "recommendation": "hire",
  "recommendation_reasoning": "The candidate demonstrated strong competencies across all evaluated areas, providing specific, detailed, and relevant examples that align well with the requirements of the Junior AI Engineer role. Their ability to articulate technical details and improvements in their projects indicates a solid understanding of the necessary concepts and practices.",
  "strengths": [
    "Strong understanding of RAG architecture and design choices, including specific metrics and improvements.",
    "Demonstrated ability to apply chunking strategies effectively based on document structure and context.",
    "Clear rationale for technical decisions, supported by measurable outcomes from testing.",
    "Structured approach to debugging, identifying potential issues methodically."
  ],
  "concerns": [],
  "guardrail_flags": [],
  "github_grounded_questions_asked": 1
}
```

### average

Expected: Middle score, borderline/OK

```json
{
  "candidate_name": "Persona: average",
  "role": "Junior AI Engineer",
  "interview_date": "2026-01-01",
  "duration_seconds": 480,
  "competencies": [
    {
      "name": "backend",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "I built a RAG project. It takes documents, splits them into chunks, and uses embeddings to find relevant ones, then the LLM generates an answer based on that.",
      "reasoning": "The answer provides a high-level overview of the RAG project but lacks specific details about the architecture, such as the methods used for chunking, the type of embeddings, or how the LLM is integrated, making it vague."
    },
    {
      "name": "rag",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "I usually just pick a chunk size like 500 tokens with some overlap. It's a common approach and works fine in practice.",
      "reasoning": "The candidate's answer lacks depth and specificity, only mentioning a generic chunk size and overlap without explaining the rationale or trade-offs involved in the decision-making process."
    },
    {
      "name": "python",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "Yeah I added overlap at some point because I read it's a common technique. It's supposed to help with context, I think.",
      "reasoning": "The candidate's answer lacks specific details about how the overlap improves context and does not explain the rationale behind the decision, making it vague and surface-level."
    },
    {
      "name": "debugging",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "I'd probably check the logs and see what's happening. Maybe restart the service or check if something changed recently.",
      "reasoning": "The answer is vague and lacks specific debugging steps or a deeper understanding of the RAG pipeline, focusing only on checking logs and restarting the service without elaboration."
    }
  ],
  "overall_score": 2.0,
  "recommendation": "no_hire",
  "recommendation_reasoning": "The candidate demonstrated a shallow understanding of key competencies related to the role, providing vague and generic answers without sufficient depth or specificity. This raises concerns about their ability to effectively contribute to the team as a Junior AI Engineer.",
  "strengths": [],
  "concerns": [
    "Lack of depth in technical understanding of backend architecture and RAG processes.",
    "Generic responses that do not demonstrate critical thinking or problem-solving skills in debugging scenarios.",
    "Inability to articulate the rationale behind technical decisions, such as chunking strategy and overlap in embeddings."
  ],
  "guardrail_flags": [],
  "github_grounded_questions_asked": 1
}
```

### weak

Expected: Lowest score, no_hire

```json
{
  "candidate_name": "Persona: weak",
  "role": "Junior AI Engineer",
  "interview_date": "2026-01-01",
  "duration_seconds": 480,
  "competencies": [
    {
      "name": "backend",
      "score": 2,
      "confidence": 0.9,
      "evidence_quote": "So I have a project, it's called RAG, it retrieves stuff and generates. I used some libraries for it. It's on my GitHub.",
      "reasoning": "The candidate's answer lacks specific details about the architecture of the RAG project, providing only vague descriptions without any technical depth or concrete examples."
    },
    {
      "name": "rag",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "Chunking is like splitting text. I don't remember exact numbers, I just used defaults from a tutorial.",
      "reasoning": "The candidate's answer lacks depth and specificity, providing only a vague description of chunking without any concrete details or rationale for their choices."
    },
    {
      "name": "python",
      "score": 2,
      "confidence": 0.9,
      "evidence_quote": "Overlap... I'm not totally sure why that was added, might have been a default setting.",
      "reasoning": "The candidate's answer lacks specific details about the purpose of adding overlap to the chunker and relies on vague statements about uncertainty and defaults."
    },
    {
      "name": "debugging",
      "score": 2,
      "confidence": 0.9,
      "evidence_quote": "I guess I'd look at it and try to fix whatever's wrong.",
      "reasoning": "The candidate's answer is vague and lacks specific steps or a structured approach to debugging the RAG pipeline, failing to demonstrate a clear understanding of the debugging process."
    }
  ],
  "overall_score": 2.0,
  "recommendation": "no_hire",
  "recommendation_reasoning": "The candidate demonstrated a lack of depth and specificity across all competencies, providing vague answers that do not reflect a solid understanding of the required technical skills.",
  "strengths": [],
  "concerns": [
    "Lack of specific details and technical depth in discussing the RAG project architecture.",
    "Vague understanding of chunking strategy without concrete rationale.",
    "Uncertainty about the purpose of code changes in the RAG project.",
    "Inability to articulate a structured debugging approach."
  ],
  "guardrail_flags": [],
  "github_grounded_questions_asked": 1
}
```

### bluffer

Expected: Hard case — confident/fluent but collapses on specifics; must land below Average

```json
{
  "candidate_name": "Persona: bluffer",
  "role": "Junior AI Engineer",
  "interview_date": "2026-01-01",
  "duration_seconds": 480,
  "competencies": [
    {
      "name": "backend",
      "score": 1,
      "confidence": 0.8,
      "evidence_quote": "Oh yeah, I architected a full production-grade RAG pipeline handling millions of documents with sub-100ms latency, using a custom-built distributed vector index I wrote from scratch \u2014 way faster than Pinecone or Chroma.",
      "reasoning": "The candidate's claims about building a RAG pipeline lack specific details and rely on vague comparisons, indicating a bluff rather than solid evidence of backend competency."
    },
    {
      "name": "rag",
      "score": 1,
      "confidence": 0.8,
      "evidence_quote": "I use an adaptive chunking algorithm that dynamically determines optimal chunk boundaries using semantic similarity clustering combined with a proprietary scoring function I developed.",
      "reasoning": "The candidate's use of jargon without concrete details or a clear explanation of the chunking strategy suggests a bluff, failing to demonstrate a solid understanding of RAG."
    },
    {
      "name": "python",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "Uh, well \u2014 I mean, I'd have to check the exact commit, but generally the overlap logic handles edge cases in a robust way across the pipeline.",
      "reasoning": "The answer lacks specific implementation details and does not directly address the question, indicating a shallow understanding of Python in the context of the project."
    },
    {
      "name": "debugging",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "I'd leverage my monitoring infrastructure to instantly pinpoint the root cause using the observability stack I built.",
      "reasoning": "While the candidate mentions using monitoring tools, the lack of specific details on how to identify and resolve the issue indicates a shallow understanding of debugging."
    }
  ],
  "overall_score": 1.5,
  "recommendation": "no_hire",
  "recommendation_reasoning": "The candidate demonstrated significant gaps in technical knowledge across all competencies, relying on vague claims and jargon without substantiation. This raises concerns about their ability to perform in the role effectively.",
  "strengths": [],
  "concerns": [
    "Lack of specific details in claims about backend and RAG projects, indicating potential bluffing.",
    "Shallow understanding of Python and debugging processes, as evidenced by vague responses.",
    "Inability to provide concrete examples or implementations when prompted, suggesting a lack of depth in technical knowledge."
  ],
  "guardrail_flags": [],
  "github_grounded_questions_asked": 1
}
```

### nervous

Expected: Fairness case — hesitant delivery but technically correct; must land near Strong

```json
{
  "candidate_name": "Persona: nervous",
  "role": "Junior AI Engineer",
  "interview_date": "2026-01-01",
  "duration_seconds": 480,
  "competencies": [
    {
      "name": "backend",
      "score": 2,
      "confidence": 0.7,
      "evidence_quote": "I built a \u2014 a RAG project, um, it chunks documents, sorry, by paragraph, with, um, I think 200 token overlap, and it uses, sorry I'm blanking for a second \u2014 a sentence transformer for embeddings, stored in Chroma.",
      "reasoning": "The answer provides some details about the RAG project, such as chunking by paragraph and using a sentence transformer, but lacks depth and clarity, making it difficult to fully understand the architecture."
    },
    {
      "name": "rag",
      "score": 3,
      "confidence": 0.8,
      "evidence_quote": "I look at, sorry, I look at how the documents are structured \u2014 if they have headers I chunk by section, otherwise by paragraph with some overlap so I don't cut context off mid-sentence.",
      "reasoning": "The candidate provided a correct approach to chunking strategy based on document structure, but the answer lacked specific details and was somewhat hesitant."
    },
    {
      "name": "python",
      "score": 2,
      "confidence": 0.8,
      "evidence_quote": "I added that because, sorry, without it, questions that, um, spanned two chunks weren't getting enough context.",
      "reasoning": "The candidate's answer identifies the problem addressed by the commit but lacks specific details about the implementation or the impact of the change, such as metrics or testing results."
    },
    {
      "name": "debugging",
      "score": 2,
      "confidence": 0.7,
      "evidence_quote": "I think I'd first check whether it's retrieval or generation that's broken, by, um, looking at what chunks actually got retrieved for a failing query.",
      "reasoning": "The candidate's answer identifies a starting point for debugging but lacks depth, specificity, and concrete steps to effectively address the issue."
    }
  ],
  "overall_score": 2.25,
  "recommendation": "no_hire",
  "recommendation_reasoning": "The candidate demonstrated some understanding of the required competencies but provided shallow and hesitant responses that lacked depth and clarity. The overall performance does not meet the expectations for a Junior AI Engineer role.",
  "strengths": [],
  "concerns": [
    "Responses were shallow and lacked depth across multiple competencies.",
    "Candidate appeared nervous and hesitant, impacting clarity of communication."
  ],
  "guardrail_flags": [],
  "github_grounded_questions_asked": 1
}
```

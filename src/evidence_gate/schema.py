import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUALITY_METRICS = {
    "recall_at_k",
    "mrr",
    "citation_precision",
    "quote_integrity",
    "answer_coverage",
    "abstention_accuracy",
    "collection_integrity",
    "success_rate",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Case(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    collection: str = "demo"
    relevant_documents: list[str] = Field(default_factory=list)
    expected_phrases: list[str] = Field(default_factory=list)
    should_abstain: bool = False
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        if self.should_abstain and (self.relevant_documents or self.expected_phrases):
            raise ValueError("Abstention cases must not list expected documents or phrases")
        if not self.should_abstain and (not self.relevant_documents or not self.expected_phrases):
            raise ValueError("Answerable cases require relevant documents and expected phrases")
        if any(not x.strip() for x in self.expected_phrases):
            raise ValueError("Expected phrases cannot be blank")
        return self


class Suite(StrictModel):
    name: str
    cases: list[Case] = Field(min_length=1)
    minimums: dict[str, float] = Field(
        default_factory=lambda: {
            "recall_at_k": 0.9,
            "citation_precision": 0.9,
            "quote_integrity": 1.0,
            "answer_coverage": 0.9,
            "abstention_accuracy": 1.0,
            "collection_integrity": 1.0,
            "success_rate": 1.0,
        }
    )
    max_regression: float = Field(default=0.02, ge=0, le=1)
    max_p95_ms: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_suite(self):
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate case IDs")
        if set(self.minimums) - QUALITY_METRICS:
            raise ValueError("Unknown gate metric")
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.minimums.values()):
            raise ValueError("Metric minimums must be finite values between 0 and 1")
        return self


class Citation(StrictModel):
    document_id: str
    chunk_id: str
    source: str
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Retrieved(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document_id: str
    chunk_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Prediction(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    answer: str
    abstained: bool
    citations: list[Citation]
    retrieved: list[Retrieved]
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self):
        if self.abstained and (self.answer.strip() or self.citations):
            raise ValueError("Abstained predictions must have no answer or citations")
        if not self.abstained and not self.answer.strip():
            raise ValueError("Non-abstained predictions need answer text")
        return self


class Configuration(StrictModel):
    top_k: int = Field(default=3, ge=1, le=20)
    mode: Literal["lexical", "hybrid"] = "lexical"
    answerer: Literal["extractive", "ollama"] = "extractive"

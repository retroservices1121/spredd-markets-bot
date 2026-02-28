import { useState, useCallback } from "react";
import { submitEvent, type SubmitEventRequest } from "@/api/client";

interface FormData {
  question: string;
  description: string;
  category: string;
  end_date: string;
  resolution_source: string;
}

interface UseCreateEventReturn {
  step: number;
  formData: FormData;
  updateField: <K extends keyof FormData>(key: K, value: FormData[K]) => void;
  nextStep: () => void;
  prevStep: () => void;
  submitting: boolean;
  error: string | null;
  success: boolean;
  handleSubmit: () => Promise<void>;
  reset: () => void;
}

const INITIAL_FORM: FormData = {
  question: "",
  description: "",
  category: "",
  end_date: "",
  resolution_source: "",
};

export function useCreateEvent(): UseCreateEventReturn {
  const [step, setStep] = useState(0);
  const [formData, setFormData] = useState<FormData>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const updateField = useCallback(<K extends keyof FormData>(key: K, value: FormData[K]) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }, []);

  const nextStep = useCallback(() => setStep((s) => Math.min(s + 1, 2)), []);
  const prevStep = useCallback(() => setStep((s) => Math.max(s - 1, 0)), []);

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const req: SubmitEventRequest = {
        question: formData.question,
        description: formData.description,
        category: formData.category,
        end_date: formData.end_date,
        resolution_source: formData.resolution_source || undefined,
      };
      await submitEvent(req);
      setSuccess(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to submit event");
    } finally {
      setSubmitting(false);
    }
  }, [formData]);

  const reset = useCallback(() => {
    setStep(0);
    setFormData(INITIAL_FORM);
    setSubmitting(false);
    setError(null);
    setSuccess(false);
  }, []);

  return {
    step,
    formData,
    updateField,
    nextStep,
    prevStep,
    submitting,
    error,
    success,
    handleSubmit,
    reset,
  };
}

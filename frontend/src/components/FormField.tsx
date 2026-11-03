import type { ReactNode } from 'react';

interface FormFieldProps {
  label: string;
  required?: boolean;
  error?: string | null;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}

export function FormField({ label, required, error, hint, children, htmlFor }: FormFieldProps) {
  return (
    <div className="form-field">
      <label htmlFor={htmlFor}>
        {label}
        {required && <span className="required">*</span>}
      </label>
      {children}
      {error && <div className="mt-1 text-sm text-danger">{error}</div>}
      {!error && hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

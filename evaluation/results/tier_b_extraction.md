# Tier B extraction accuracy

Synthetic PDFs only. This report is not combined with Tier A.
Subset: 30 cases, stratified by family and category, seed 42.
document_copy is ignored. A field is correct when the extracted value matches the manifest ground truth.

family | doc_type | documents | fields | correct | accuracy
--- | --- | --- | --- | --- | ---
project | invoice | 135 | 675 | 675 | 1.0000
project | progress_report | 140 | 560 | 560 | 1.0000
project | tender_award_notice | 15 | 150 | 150 | 1.0000
project | work_order | 15 | 60 | 60 | 1.0000
property_tax | assessment_form | 15 | 165 | 164 | 0.9939
property_tax | payment_receipt | 15 | 180 | 179 | 0.9944
property_tax | tax_bill | 15 | 225 | 224 | 0.9956
all | all |  | 2015 | 2012 | 0.9985

## Failure reasons

- value_mismatch: 3

## Examples

- property_tax PID00035 assessment_form address: extracted='H.No. 367, Khosla Circle, Pallavaram 01' ground_truth='H.No. 367, Khosla Circle, Pallavaram 014363'
- property_tax PID00035 tax_bill address: extracted='H.No. 367, Khosla Circle, Pallavaram 01' ground_truth='H.No. 367, Khosla Circle, Pallavaram 014363'
- property_tax PID00035 payment_receipt address: extracted='H.No. 367, Khosla Circle, Pallavaram 01' ground_truth='H.No. 367, Khosla Circle, Pallavaram 014363'

## Tokens

Cached calls were not sent to the provider. Live cost uses the configured per-million rates, which are the OpenAI rates and are not a Groq bill.

- cached calls=350 input=86137 output=65928 cost_usd=0.000000
- live calls=0 input=0 output=0 cost_usd=0.000000

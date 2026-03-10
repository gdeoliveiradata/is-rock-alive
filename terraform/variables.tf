variable "PROJECT_ID" {
  type        = string
  description = "ID of GCP Project."
}

variable "PROJECT_REGION" {
  type        = string
  description = "Region of the GCP Project."
  default     = "us-central1"
}

variable "PROJECT_ZONE" {
  type        = string
  description = "Zone of the GCP Project."
  default     = "us-central1-c"
}
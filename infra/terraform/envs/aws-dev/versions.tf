terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.70" }
    random = { source = "hashicorp/random", version = "~> 3.9" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "euron-workflow-engine"
      Environment = "aws-dev"
      ManagedBy   = "terraform"
    }
  }
}

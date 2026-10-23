# The public entry point: one Application Load Balancer for the web app and the API,
# routed by host name (app., api.), a TLS certificate for those names, DNS records, and
# an optional WAF in front of both.
locals {
  hostnames  = [for h in values(var.hostnames) : h]
  manage_dns = var.route53_zone_id != null
}

# --- Certificate -------------------------------------------------------------

resource "aws_acm_certificate" "this" {
  count                     = var.certificate_arn == null ? 1 : 0
  domain_name               = local.hostnames[0]
  subject_alternative_names = slice(local.hostnames, 1, length(local.hostnames))
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = var.certificate_arn == null && local.manage_dns ? {
    for o in aws_acm_certificate.this[0].domain_validation_options : o.domain_name => o
  } : {}
  zone_id         = var.route53_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count                   = var.certificate_arn == null && local.manage_dns ? 1 : 0
  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

locals {
  certificate_arn = var.certificate_arn != null ? var.certificate_arn : (
    local.manage_dns ? aws_acm_certificate_validation.this[0].certificate_arn : aws_acm_certificate.this[0].arn
  )
}

# --- Load balancer -----------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "HTTPS into the load balancer"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name_prefix}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "public" {
  #checkov:skip=CKV_AWS_260:Port 80 only answers with a 301 to HTTPS (see the http listener).
  for_each          = toset(["80", "443"])
  security_group_id = aws_security_group.alb.id
  description       = "HTTP/HTTPS from the internet (80 only redirects)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}

resource "aws_lb" "this" {
  #checkov:skip=CKV2_AWS_28:WAF is an input (enable_waf); aws-prod enables it.
  #checkov:skip=CKV2_AWS_76:WAF is an input (enable_waf); when enabled it runs AWSManagedRulesKnownBadInputsRuleSet, which blocks Log4j lookups.
  #checkov:skip=CKV_AWS_150:Deletion protection is an input (deletion_protection); aws-prod enables it.
  name                       = "${var.name_prefix}-alb"
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  # A webhook that answers when its run finishes (response: when_finished) holds the
  # request open for at most 25 seconds, well inside the timeout.
  idle_timeout               = 60
  enable_deletion_protection = var.deletion_protection

  #checkov:skip=CKV_AWS_91:Access logging is opt-in via access_logs_bucket.
  dynamic "access_logs" {
    for_each = var.access_logs_bucket == null ? [] : [1]
    content {
      bucket  = var.access_logs_bucket
      prefix  = "alb"
      enabled = true
    }
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Unknown host names get a 404; each service adds its own host rule.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Not found"
      status_code  = "404"
    }
  }
}

# --- WAF ---------------------------------------------------------------------

resource "aws_wafv2_web_acl" "this" {
  #checkov:skip=CKV2_AWS_31:WAF logging needs a Firehose or bucket the operator chooses.
  count       = var.enable_waf ? 1 : 0
  name        = "${var.name_prefix}-waf"
  description = "Managed protections and a per-IP rate limit in front of WorkflowEngine"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Known bad inputs (including the Log4j JNDI lookups) is spelled out on its own, so policy
  # scanners can see it; the other managed groups follow below.
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 20
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesKnownBadInputsRuleSet"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = {
      AWSManagedRulesCommonRuleSet          = 10
      AWSManagedRulesAmazonIpReputationList = 30
    }
    content {
      name     = rule.key
      priority = rule.value
      override_action {
        none {}
      }
      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.key
          # Webhook payloads and workflow definitions are larger than the rule's 8 KB body
          # limit; the API enforces its own limits (WEBHOOK_MAX_BODY_KB, MAX_PAYLOAD_KB).
          dynamic "rule_action_override" {
            for_each = rule.key == "AWSManagedRulesCommonRuleSet" ? ["SizeRestrictions_BODY"] : []
            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = true
      }
    }
  }

  rule {
    name     = "rate-limit"
    priority = 40
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "this" {
  count        = var.enable_waf ? 1 : 0
  resource_arn = aws_lb.this.arn
  web_acl_arn  = aws_wafv2_web_acl.this[0].arn
}

# --- DNS (when the zone is in Route53) ---------------------------------------

resource "aws_route53_record" "hosts" {
  for_each = local.manage_dns ? var.hostnames : {}
  zone_id  = var.route53_zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}

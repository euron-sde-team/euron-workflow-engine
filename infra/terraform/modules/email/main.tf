# The SES v2 identity the email node sends from (MAIL_FROM must use it) and, on AWS, a
# configuration set that requires TLS, tracks reputation and suppresses addresses that
# bounced or complained. A domain identity publishes its DKIM records when the zone is in
# Route53; an address identity is verified by the link SES mails to it.
#
# Locally the same module runs against Floci, which relays every message to Mailpit.
locals {
  is_domain = !strcontains(var.identity, "@")
}

resource "aws_sesv2_configuration_set" "this" {
  count                  = var.create_configuration_set ? 1 : 0
  configuration_set_name = "${var.name_prefix}-mail"

  delivery_options {
    tls_policy = "REQUIRE"
  }
  reputation_options {
    reputation_metrics_enabled = true
  }
  sending_options {
    sending_enabled = true
  }
  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_email_identity" "this" {
  email_identity         = var.identity
  configuration_set_name = var.create_configuration_set ? aws_sesv2_configuration_set.this[0].configuration_set_name : null
}

resource "aws_route53_record" "dkim" {
  count   = local.is_domain && var.route53_zone_id != null ? 3 : 0
  zone_id = var.route53_zone_id
  name    = "${aws_sesv2_email_identity.this.dkim_signing_attributes[0].tokens[count.index]}._domainkey.${var.identity}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_sesv2_email_identity.this.dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

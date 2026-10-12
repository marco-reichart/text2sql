module "global_label" {
  source  = "cloudposse/label/null"
  version = "0.25.0"

  name            = var.name
  environment     = var.environment
  id_length_limit = 64
  tags            = var.default_tags
}

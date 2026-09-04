output "alb_url" {
  value = "http://${aws_lb.app.dns_name}"
}

output "alb_dns" {
  value = aws_lb.app.dns_name
}

output "rds_endpoint" {
  value = aws_db_instance.mysql.address
}

output "s3_bucket" {
  value = aws_s3_bucket.app_bucket.bucket
}

output "vpc_id" {
  value = aws_vpc.main.id
}

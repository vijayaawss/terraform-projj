resource "aws_db_subnet_group" "mysql" {
  name = "${var.project_name}-db-subnet"

  subnet_ids = [
    aws_subnet.db_1.id,
    aws_subnet.db_2.id
  ]

  tags = {
    Name = "${var.project_name}-db-subnet"
  }
}

resource "aws_db_instance" "mysql" {
  identifier = "${var.project_name}-mysql"

  engine         = "mysql"
  engine_version = "8.0"
  instance_class = "db.t3.micro"

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  port = 3306

  db_subnet_group_name = aws_db_subnet_group.mysql.name

  vpc_security_group_ids = [
    aws_security_group.rds.id
  ]

  publicly_accessible = false
  multi_az            = true

  backup_retention_period = 7
  skip_final_snapshot     = true
}

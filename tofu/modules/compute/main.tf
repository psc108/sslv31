data "aws_ami" "ubuntu_2404" {
  most_recent = true
  owners      = ["099720109477"]
  filter { name = "name";              values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"] }
  filter { name = "virtualization-type"; values = ["hvm"] }
  filter { name = "architecture";      values = ["x86_64"] }
}

data "aws_ami" "rhel_9" {
  most_recent = true
  owners      = ["309956199498"]
  filter { name = "name";              values = ["RHEL-9.*_HVM-*-x86_64-*"] }
  filter { name = "virtualization-type"; values = ["hvm"] }
}

resource "aws_key_pair" "build_manager" {
  key_name   = "${var.environment_name}-build-manager"
  public_key = var.ssh_public_key
  tags       = { Name = "${var.environment_name}-build-manager-key" }
}

resource "aws_iam_role" "ec2_instance" {
  name = "${var.environment_name}-ec2-instance-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole"; Effect = "Allow"; Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ec2_instance.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy" "s3_artefacts" {
  count = var.artefacts_bucket != "" ? 1 : 0
  name  = "${var.environment_name}-s3-artefacts"
  role  = aws_iam_role.ec2_instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow"; Action = ["s3:GetObject", "s3:ListBucket"]; Resource = ["arn:aws:s3:::${var.artefacts_bucket}", "arn:aws:s3:::${var.artefacts_bucket}/*"] }]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.environment_name}-ec2-profile"
  role = aws_iam_role.ec2_instance.name
}

resource "aws_instance" "host" {
  for_each = { for k, v in var.hosts : k => v if v.service_role != "bastion" }

  ami                    = each.value.os_type == "rhel" ? data.aws_ami.rhel_9.id : data.aws_ami.ubuntu_2404.id
  instance_type          = each.value.instance_type
  subnet_id              = var.private_subnet_ids[each.value.az_index % length(var.private_subnet_ids)]
  vpc_security_group_ids = [var.sg_app_id]
  key_name               = aws_key_pair.build_manager.key_name
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = each.value.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = base64encode(templatefile("${path.module}/templates/userdata.sh.tpl", {
    hostname       = each.key
    ssh_public_key = var.ssh_public_key
    os_type        = each.value.os_type
  }))

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name        = "${var.environment_name}-${each.key}"
    Role        = each.value.service_role
    OsType      = each.value.os_type
    AnsibleHost = each.key
  }
}

# Bastion host (optional)
resource "aws_security_group" "bastion" {
  count       = var.create_bastion ? 1 : 0
  name        = "${var.environment_name}-sg-bastion"
  description = "Bastion — SSH from management CIDRs only"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = length(var.management_cidrs) > 0 ? [1] : []
    content { from_port = 22; to_port = 22; protocol = "tcp"; cidr_blocks = var.management_cidrs }
  }
  egress { from_port = 0; to_port = 0; protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }
  tags = { Name = "${var.environment_name}-sg-bastion" }
}

resource "aws_instance" "bastion" {
  count = var.create_bastion ? 1 : 0

  ami                         = data.aws_ami.ubuntu_2404.id
  instance_type               = "t3.micro"
  subnet_id                   = var.public_subnet_ids[0]
  vpc_security_group_ids      = [aws_security_group.bastion[0].id]
  key_name                    = aws_key_pair.build_manager.key_name
  associate_public_ip_address = true

  metadata_options { http_tokens = "required" }
  tags = { Name = "${var.environment_name}-bastion"; Role = "bastion" }
}

resource "aws_eip" "bastion" {
  count    = var.create_bastion ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.bastion[0].id
  tags     = { Name = "${var.environment_name}-bastion-eip" }
}

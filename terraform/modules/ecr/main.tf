
# ECR Repository
resource "aws_ecr_repository" "main" {
  for_each = var.repository_names

  name = "${var.name}-${var.environment}-${each.key}"

  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.name}-${var.environment}-${each.key}"
  }
}


# ECR Lifecycle Policy
resource "aws_ecr_lifecycle_policy" "main" {
  for_each = aws_ecr_repository.main

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Delete untagged images after 1 day"

        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }

        action = {
          type = "expire"
        }
      },
      {
        # main 머지마다 CI가 모든 저장소에 새 태그를 올리므로, 배포에 고정된 태그가 밀려 지워지지 않게 넉넉히 둔다.
        rulePriority = 2
        description  = "Keep latest 30 tagged images"

        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 30
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}

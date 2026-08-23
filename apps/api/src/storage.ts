import {
  GetObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

import type { ApiConfig } from "./config.js";

export class ObjectStorage {
  private readonly client: S3Client;
  private readonly publicClient: S3Client;

  public constructor(private readonly config: ApiConfig) {
    const clientOptions = {
      region: config.S3_REGION,
      forcePathStyle: config.S3_FORCE_PATH_STYLE,
      credentials: {
        accessKeyId: config.S3_ACCESS_KEY_ID,
        secretAccessKey: config.S3_SECRET_ACCESS_KEY,
      },
    };
    this.client = new S3Client({
      ...clientOptions,
      endpoint: config.S3_ENDPOINT,
    });
    this.publicClient = new S3Client({
      ...clientOptions,
      endpoint: config.S3_PUBLIC_ENDPOINT ?? config.S3_ENDPOINT,
    });
  }

  public presignUpload(
    key: string,
    contentType: string,
    bytes: number,
  ): Promise<string> {
    return getSignedUrl(
      this.publicClient,
      new PutObjectCommand({
        Bucket: this.config.S3_BUCKET,
        Key: key,
        ContentType: contentType,
        ContentLength: bytes,
        ServerSideEncryption: "AES256",
      }),
      { expiresIn: this.config.SIGNED_URL_TTL_SECONDS },
    );
  }

  public presignDownload(key: string): Promise<string> {
    return getSignedUrl(
      this.publicClient,
      new GetObjectCommand({ Bucket: this.config.S3_BUCKET, Key: key }),
      { expiresIn: this.config.SIGNED_URL_TTL_SECONDS },
    );
  }
}

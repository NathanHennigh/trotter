import { Asset } from 'expo-asset';
import { Image, Platform } from 'react-native';
import * as THREE from 'three';

type RendererOptions = THREE.WebGLRendererParameters & {
  gl: WebGLRenderingContext;
  pixelRatio?: number;
  clearColor?: THREE.ColorRepresentation;
  width?: number;
  height?: number;
};

type AssetReference = number | string | Asset | { uri: string };

async function resolveAsset(reference: AssetReference) {
  let asset: Asset;

  if (reference instanceof Asset) {
    asset = reference;
  } else if (typeof reference === 'number') {
    asset = Asset.fromModule(reference);
  } else if (typeof reference === 'string') {
    asset = Asset.fromURI(reference);
  } else if (reference?.uri) {
    asset = Asset.fromURI(reference.uri);
  } else {
    throw new Error(`Cannot resolve asset automatically: ${String(reference)}`);
  }

  const needsNativeFile = Platform.OS !== 'web' && !asset.localUri?.startsWith('file://');
  if (!asset.localUri || needsNativeFile) {
    // Android image requires resolve to resource identifiers. Expo GL can only
    // decode a file URI, so force expo-asset to copy the resource into cache.
    if (needsNativeFile) {
      asset.localUri = null;
      asset.downloaded = false;
    }
    await asset.downloadAsync();
  }

  if (Platform.OS !== 'web' && !asset.localUri?.startsWith('file://')) {
    throw new Error(`Texture asset did not resolve to a local file: ${asset.uri}`);
  }

  return asset;
}

export class ExpoRenderer extends THREE.WebGLRenderer {
  constructor({ gl, pixelRatio = 1, clearColor, width, height, canvas, ...options }: RendererOptions) {
    const rendererCanvas = canvas ?? {
      width: gl.drawingBufferWidth,
      height: gl.drawingBufferHeight,
      clientHeight: gl.drawingBufferHeight,
      style: {},
      addEventListener() {},
      removeEventListener() {},
    };

    super({
      ...options,
      canvas: rendererCanvas as HTMLCanvasElement,
      context: gl,
    });

    this.setPixelRatio(pixelRatio);
    if (width && height) this.setSize(width, height);
    if (clearColor) this.setClearColor(clearColor);
  }
}

export class ExpoTextureLoader extends THREE.TextureLoader {
  override load(
    reference: AssetReference,
    onLoad?: (texture: THREE.Texture) => void,
    onProgress?: (event: ProgressEvent) => void,
    onError?: (error: unknown) => void,
  ) {
    const texture = new THREE.Texture();

    void resolveAsset(reference)
      .then(async (asset) => {
        const uri = asset.localUri ?? asset.uri;

        if (Platform.OS === 'web') {
          new THREE.ImageLoader(this.manager).load(
            uri,
            (image) => {
              texture.image = image;
              texture.needsUpdate = true;
              onLoad?.(texture);
            },
            onProgress,
            onError,
          );
          return;
        }

        let width = asset.width;
        let height = asset.height;
        if (!width || !height) {
          const size = await new Promise<{ width: number; height: number }>((resolve, reject) => {
            Image.getSize(uri, (imageWidth, imageHeight) => resolve({ width: imageWidth, height: imageHeight }), reject);
          });
          width = size.width;
          height = size.height;
        }

        Object.assign(texture, { isDataTexture: true });
        texture.image = { data: asset, width, height };
        texture.needsUpdate = true;
        onLoad?.(texture);
      })
      .catch((error: unknown) => onError?.(error));

    return texture;
  }
}

declare module 'expo-three' {
  export class TextureLoader {
    load(
      asset: any,
      onLoad?: (texture: any) => void,
      onProgress?: (event: any) => void,
      onError?: (event: any) => void,
    ): any;
  }

  export class Renderer {
    constructor(options: { gl: any; antialias?: boolean });
    setSize(width: number, height: number): void;
    render(scene: any, camera: any): void;
  }
}

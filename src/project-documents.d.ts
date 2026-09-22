declare module "regear:project-documents" {
  export const noticesText:string;
  export const licenseText:string;
}

declare module "*.svg?rich-sprite" {
  const sprite: string;
  export default sprite;
}

declare module "*.svg?v3-tile" {
  const image: string;
  export default image;
}

import type { ComponentRecordType } from '@vben/types';

import type { RouteRecordRaw } from 'vue-router';
import esopPublicRoutes from '../modules/esop/public-routes';
export const modulePublicRoutes: RouteRecordRaw[] = [...esopPublicRoutes];

export const modulePageMap: ComponentRecordType = {
  ...import.meta.glob('../modules/erp/views/**/*.vue'),
  ...import.meta.glob('../modules/esop/views/**/*.vue'),
};
